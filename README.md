# watcher_operator

Kubernetes 2-node HA 환경에서 local-path 기반 PV/PVC 워크로드를 active storage node에만 스케줄링하고, 향후 failover 절차까지 Kubernetes-native하게 제어하기 위한 Python 오퍼레이터 설계 문서입니다.

이 문서의 리소스 이름, 라벨, StorageClass 이름은 모두 예시입니다. 실제 제품명이나 사내 솔루션명을 직접 사용하지 않도록 중립적인 명칭을 사용합니다.

## 배경

대상 클러스터는 2대의 노드로 구성되며, 두 노드 모두 master/control-plane 노드로 조인된 특수한 구조입니다. 외부 복제 솔루션이 양쪽 노드의 동일한 경로에 볼륨 데이터를 복제하고, 특정 시점에는 한쪽 노드에만 디스크를 mount합니다.

현재 active 노드는 다음과 같은 중립적인 라벨로 표현한다고 가정합니다.

```yaml
storage-ha/role: active
```

PV/PVC를 사용하는 Pod는 반드시 이 라벨이 붙은 노드에서만 기동되어야 합니다. 이를 통해 local-path provisioner가 사용하는 hostPath 경로가 양쪽 노드에 존재하더라도, 실제로 mount된 active node 한쪽에서만 워크로드가 실행되도록 보장합니다.

## 현재 PV 구조

초기 설치 후 생성된 PV는 다음과 유사한 특징을 가집니다.

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  annotations:
    local.path.provisioner/selected-node: node-a
    pv.kubernetes.io/provisioned-by: rancher.io/local-path
spec:
  accessModes:
    - ReadWriteOnce
  hostPath:
    path: /data/local-volumes/cluster-a/...
    type: DirectoryOrCreate
  persistentVolumeReclaimPolicy: Retain
  storageClassName: local-path-ha
```

확인된 PV에는 `spec.nodeAffinity`가 없었습니다. 따라서 Kubernetes 스케줄러는 해당 PV를 특정 노드에 고정된 볼륨으로 판단하지 않습니다.

이 구조에서는 PV 자체를 patch하기보다, PV/PVC를 사용하는 워크로드의 Pod template에 node affinity를 주입하는 방식이 적합합니다.

## 대상 범위

초기 대상은 다음 조건을 만족하는 워크로드입니다.

- HA local-path StorageClass를 사용하는 PVC를 참조하는 워크로드
- `rancher.io/local-path` local-path provisioner로 생성된 PV/PVC
- `Deployment`
- `StatefulSet`
- 향후 필요 시 `DaemonSet`, `Job`, `CronJob` 확장

특히 `StatefulSet.spec.volumeClaimTemplates`로 생성되는 PVC를 반드시 고려해야 합니다.

## 스케줄링 정책

PV/PVC 사용 Pod는 active storage node로만 스케줄되어야 합니다.

기본 주입 정책은 다음과 같습니다.

```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: storage-ha/role
              operator: In
              values:
                - active
```

`requiredDuringSchedulingIgnoredDuringExecution`는 스케줄링 시점에만 적용됩니다. 이미 실행 중인 Pod는 노드 라벨이 변경되어도 자동으로 이동하지 않습니다. 따라서 failover 시에는 기존 방식처럼 replica를 `0`으로 낮춰 Pod를 종료한 뒤, 새 active node에서 다시 기동시키는 흐름이 필요합니다.

## Mount 상태 검증

`storage-ha/role=active` 라벨은 active 역할을 의미하지만, 실제 디스크 mount 완료 여부를 보장하지는 않습니다. 라벨이 먼저 붙고 mount가 늦게 완료되면 Pod가 잘못된 시점에 기동될 수 있습니다.

따라서 최종적으로는 다음과 같이 역할 라벨과 준비 상태 라벨을 분리하는 것이 안전합니다.

```yaml
storage-ha/role: active
storage-ha/ready: "true"
```

권장 스케줄링 조건은 다음 두 조건을 모두 만족하는 노드입니다.

- `storage-ha/role=active`
- `storage-ha/ready=true`

mount 상태 확인은 중앙 오퍼레이터가 직접 수행하기 어렵기 때문에, 각 노드에서 실행되는 Node Agent DaemonSet을 두는 구조가 적합합니다.

Node Agent의 책임은 다음과 같습니다.

- mount path가 실제 mountpoint인지 확인
- read/write 가능 여부 확인
- 필요 시 복제 솔루션의 primary 상태 확인
- 자기 노드의 ready 상태를 Node label 또는 CRD status로 보고
- heartbeat를 주기적으로 갱신

## 기존 Failover 절차

현재 외부 솔루션은 다음 절차로 failover를 수행합니다.

1. 모니터링 서비스가 PV를 사용하는 Pod 수를 감시합니다.
2. 기대 Pod 수와 실제 Pod 수가 불일치하면 비정상 상태로 간주합니다.
3. failover 절차를 시작합니다.
4. shell script에 정의된 모듈 의존성 순서에 따라 PV 사용 워크로드의 replica를 `0`으로 변경합니다.
5. active node의 `storage-ha/role=active` 라벨을 제거합니다.
6. 디스크를 unmount합니다.
7. 복제 볼륨의 primary 노드를 반대편 노드로 전환합니다.
8. 새 active node에 디스크를 mount합니다.
9. shell script로 새 노드에 `storage-ha/role=active` 라벨을 할당합니다.
10. 기존 replica 수를 원복합니다.
11. 모니터링 스크립트를 다시 기동합니다.

## 오퍼레이터 방향

오퍼레이터는 기존 shell script 기반 failover를 한 번에 대체하기보다, 단계적으로 Kubernetes-native 컨트롤러로 흡수하는 방향이 적합합니다.

### v1

- HA local-path PVC 사용 워크로드 감지
- Pod template에 required node affinity 자동 주입
- 관리 대상 namespace와 workload 필터링
- 기존 affinity와 label을 보존하며 병합
- ready node가 정확히 1개인지 확인
- mount 상태는 Node Agent를 통해 보고
- 비정상 상태를 Event, log, CRD status로 기록

### v2

- shell script의 replica `0` 설정과 replica 원복을 Kubernetes API patch로 대체
- 워크로드 의존성 순서 지원
- failover 상태 머신 도입
- 외부 복제 솔루션의 unmount, promote, mount 명령은 Job 또는 command hook으로 연동

### v3

- 전체 failover orchestration을 오퍼레이터가 담당
- 자동/수동 failover 정책 지원
- 실패 시 rollback 또는 operator-assisted recovery 지원
- Prometheus metrics와 alerting 제공

## Failover 상태 머신

failover는 단순 함수 호출이 아니라, 중간 실패와 오퍼레이터 재시작을 견딜 수 있는 상태 머신으로 관리해야 합니다.

예상 phase는 다음과 같습니다.

```text
Normal
DetectingFailure
DrainingWorkloads
RemovingReadyLabel
RemovingRoleLabel
UnmountingDisk
PromotingReplicaVolume
MountingDisk
MarkingNodeActive
WaitingForMountReady
RestoringReplicas
Verifying
Completed
Failed
```

각 단계는 idempotent해야 합니다.

- 이미 replica가 `0`이면 drain 성공으로 처리
- 이미 label이 제거되어 있으면 label 제거 성공으로 처리
- 이미 unmount되어 있으면 unmount 성공으로 처리
- 이미 mount되어 있으면 mount 성공으로 처리
- 이미 replica가 원복되어 있으면 restore 성공으로 처리

## CRD 설계 초안

### StoragePolicy

스토리지 정책과 감시 범위를 정의합니다.

```yaml
apiVersion: storage-ha.example.com/v1alpha1
kind: StoragePolicy
metadata:
  name: default
spec:
  storageClassName: local-path-ha
  activeNodeLabel:
    key: storage-ha/role
    value: active
  readyNodeLabel:
    key: storage-ha/ready
    value: "true"
  mountPath: /data/local-volumes/cluster-a
  namespaces:
    - app-system
```

### StorageFailover

failover 요청과 진행 상태를 기록합니다.

```yaml
apiVersion: storage-ha.example.com/v1alpha1
kind: StorageFailover
metadata:
  name: failover-20260517
spec:
  targetNode: node-b
  reason: pod-count-mismatch
  mode: Automatic
status:
  phase: DrainingWorkloads
  sourceNode: node-a
  originalReplicas:
    - kind: StatefulSet
      namespace: app-system
      name: database
      replicas: 1
```

## 워크로드 의존성

기존 shell script에 들어 있는 모듈 의존성 순서는 오퍼레이터가 이해할 수 있는 데이터 모델로 분리해야 합니다.

초기에는 annotation 방식을 사용할 수 있습니다.

```yaml
metadata:
  annotations:
    storage-ha/failover-order: "10"
    storage-ha/restore-order: "90"
```

운영 안정성을 높이려면 정책 CRD에 명시적으로 정의하는 방식이 더 적합합니다.

```yaml
workloadOrder:
  - kind: Deployment
    namespace: app-system
    name: api-server
    drainOrder: 10
    restoreOrder: 90
  - kind: StatefulSet
    namespace: app-system
    name: database
    drainOrder: 20
    restoreOrder: 80
```

## HA 설계

이 오퍼레이터는 클러스터의 핵심 서비스들이 정상 동작하기 위한 제어 평면이므로, 오퍼레이터 자체도 HA 구성이 필요합니다.

권장 구성은 다음과 같습니다.

- Operator Deployment `replicas: 2`
- 두 노드에 분산 배치
- leader election 필수
- leader만 failover 상태 머신 실행
- follower는 standby로 대기
- leader 장애 시 follower가 Lease를 획득하고 진행 중인 failover를 이어서 처리

동시에 두 인스턴스가 failover를 실행하면 split-brain 위험이 있으므로, 실제 변경 작업은 반드시 단일 leader만 수행해야 합니다.

leader가 재시작되거나 교체되어도 이어서 처리할 수 있도록 상태는 메모리가 아니라 Kubernetes API에 저장해야 합니다.

- `StorageFailover.status.phase`
- `StorageFailover.status.originalReplicas`
- `StorageFailover.status.sourceNode`
- `StorageFailover.status.targetNode`
- `StorageFailover.status.lastCompletedStep`

## Operator 배치 고려사항

오퍼레이터와 Node Agent는 control-plane taint를 toleration해야 할 수 있습니다.

```yaml
tolerations:
  - key: node-role.kubernetes.io/control-plane
    operator: Exists
    effect: NoSchedule
  - key: node-role.kubernetes.io/master
    operator: Exists
    effect: NoSchedule
```

오퍼레이터는 자기 자신을 관리 대상에서 제외해야 합니다.

- 오퍼레이터는 가능하면 PV/PVC를 사용하지 않습니다.
- 오퍼레이터 namespace는 reconcile 대상에서 제외합니다.
- 오퍼레이터 Deployment는 failover scale down 대상에서 제외합니다.
- `storage-ha/ignore: "true"` 같은 제외 annotation을 지원합니다.

## Admission Webhook 검토

워크로드 생성 시점에 affinity 주입을 반드시 보장하려면 MutatingAdmissionWebhook을 고려할 수 있습니다.

장점:

- 생성 시점에 즉시 mutation 가능
- 잘못된 Pod template이 들어오는 것을 사전에 방지
- 정책 강제력이 높음

고려사항:

- webhook 자체도 HA로 배치해야 함
- 인증서 관리 필요
- `failurePolicy: Fail`이면 webhook 장애 시 신규 workload 생성이 막힘
- `failurePolicy: Ignore`이면 장애 시 정책 누락 가능

초기 버전은 reconcile 방식으로 시작하고, 정책 보장이 더 중요해지는 시점에 webhook을 추가하는 방향이 현실적입니다.

## 주요 위험과 대응

### Split-brain

두 노드가 동시에 active 또는 ready로 판단되면 데이터 손상 위험이 있습니다.

대응:

- ready node는 정확히 1개여야 함
- ready node가 0개 또는 2개 이상이면 fail-closed
- 자동 replica 원복 금지
- Event와 alert 발생

### Pod 수 기반 오탐

단순히 PV 사용 Pod 수가 불일치한다고 즉시 failover하면 rollout, image pull 지연, initContainer 지연, CrashLoopBackOff 등을 장애로 오인할 수 있습니다.

대응:

- Ready 상태 기준 사용
- timeout 기반 판단
- rollout/maintenance 상태 고려
- Pod가 어느 노드에 떠 있는지 확인
- mount ready 상태와 함께 판단

### Kubernetes Control Plane Quorum

2-node control-plane 구조에서는 etcd quorum 문제가 중요합니다. Kubernetes API가 살아있어야 오퍼레이터도 동작할 수 있습니다.

대응:

- etcd 구성이 2-member인지, 외부 etcd 또는 witness가 있는지 확인
- API server 장애는 오퍼레이터만으로 해결할 수 없음을 아키텍처 전제로 명시

## 개발 우선순위

1. Python 기반 operator 프로젝트 구조 구성
2. leader election 기반 HA operator 실행 구조 설계
3. HA local-path PVC 사용 워크로드 감지
4. Deployment, StatefulSet affinity reconcile 구현
5. Node Agent DaemonSet 설계 및 mount 상태 보고
6. CRD status 기반 failover 상태 저장
7. replica drain/restore 자동화
8. 외부 복제 솔루션 hook 연동
9. Admission Webhook 도입 검토

## Prototype 실행

정책 값은 `deploy/configmap.yaml`의 ConfigMap으로 관리하며, Deployment에서 `envFrom`으로 주입합니다. 기본 설정은 StorageClass `local-path-ha`, active 라벨 `storage-ha/role=active`, 준비 라벨 `storage-ha/ready=true`입니다.

이미지 빌드:

```sh
docker build -t watcher-operator:dev .
```

현재 프로토타입은 Kopf 기반 장기 실행 진입점으로 Deployment와 StatefulSet, PVC 이벤트를 감시하고, 대상 workload에 affinity를 patch합니다. ConfigMap 환경변수와 RBAC, Kopf peering, health probe를 포함한 기본 배포 리소스는 `deploy/`에 있습니다. 전체 Linux/클러스터 통합 검증은 별도 handoff 문서의 체크리스트를 따라 진행해야 합니다.

Linux VM에서 확인할 작업과 현재 구현 한계는 [V1_HANDOFF.md](V1_HANDOFF.md)에 정리되어 있습니다. 현재 프로토타입은 failover 자동화나 mount 상태 감시 agent를 포함하지 않습니다.

