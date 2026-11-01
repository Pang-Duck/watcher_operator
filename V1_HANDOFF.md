# V1 Development Handoff

이 문서는 현재 프로토타입에서 Linux VM 기반 v1 구현과 클러스터 검증을 이어가기 위한 작업 기록입니다. 다음 작업자는 이 문서를 먼저 읽고, 이어서 `README.md`와 현재 소스 코드를 확인합니다.

## 목적

Python Kubernetes operator를 구현해 설정된 local-path StorageClass의 PVC를 사용하는 Pod workload에 active/ready 노드 node affinity를 적용합니다. 이후 버전에서 mount 상태 확인과 failover 절차를 operator가 맡을 수 있도록 확장 가능한 기반을 마련합니다.

## 확정된 환경과 전제

- 대상은 2노드 Kubernetes 클러스터이며, 양 노드 모두 control-plane 역할을 합니다.
- 외부 복제 솔루션은 두 노드에 같은 경로로 데이터를 복제하고, 한 시점에 한 노드만 디스크를 mount합니다.
- 현재 장애 전환은 외부 monitor와 shell script가 절차적으로 수행합니다.
- 현재 failover 개요: PV 사용 workload 상태 감시 -> 의존성 순서대로 replica 0 -> active node label 제거 -> unmount -> 복제 volume의 primary 전환 -> target node mount -> label 설정 -> 원래 replica 복구 -> monitor 재기동.
- 프로토타입 예시는 사내/제품 명칭을 사용하지 않습니다. 기본 라벨은 `storage-ha/role=active`와 `storage-ha/ready=true`입니다.
- 실제 StorageClass는 설정값으로 지정합니다. 현재 예시 이름은 `local-path-ha`이며, 운영 클러스터 값으로 조정해야 합니다.
- provisioner는 Rancher local-path (`rancher.io/local-path`)입니다.
- 제공된 PV 샘플에는 `spec.nodeAffinity`가 없고 hostPath가 사용됐습니다. 복제 솔루션이 양쪽 노드에서 경로를 동일하게 제공하므로 hostPath 자체를 failover 중 수정할 계획은 없습니다.
- 오퍼레이터는 반드시 동작해야 하는 핵심 서비스로 간주합니다. HA 및 리더 선출, 재시작 후 복구 가능한 상태 저장이 필요합니다.
- 개발/통합 테스트 환경은 Windows가 아니라 Linux VM입니다. Windows 테스트 통과는 Linux 컨테이너/클러스터 동작의 증거가 아닙니다.

## 현재 프로토타입 상태

현재 구현은 순수 Python reconcile 로직에 Kopf 기반 Kubernetes controller 실행부를 추가한 프로토타입입니다. 코드는 작성됐지만 Linux 이미지 빌드 및 실제 클러스터 동작은 아직 검증되지 않았습니다.

- `src/watcher_operator/policy.py`: dataclass 정책 및 ConfigMap에서 주입되는 환경변수 파싱
- `src/watcher_operator/detector.py`: PVC StorageClass 기준 대상 판단, StatefulSet `volumeClaimTemplates` 지원
- `src/watcher_operator/affinity.py`: 기존 required nodeAffinity 조건을 유지하며 active/ready 조건 병합
- `src/watcher_operator/reconciler.py`: 대상 workload의 복사본을 reconcile한 결과 생성
- `src/watcher_operator/mount.py`: Linux `/proc/self/mountinfo`를 읽는 mountpoint 판별 함수
- `src/watcher_operator/controller.py`: Kopf startup, in-cluster/local kubeconfig, Deployment/StatefulSet/PVC handler 및 reconcile 호출
- `src/watcher_operator/__main__.py`: Kopf 장기 실행 진입점과 health endpoint
- `deploy/configmap.yaml`: 정책 환경변수
- `deploy/deployment.yaml`: 2 replica, ConfigMap, ServiceAccount, probe 및 분산 선호 설정
- `deploy/rbac.yaml`: workload/PVC 읽기·patch와 Kopf cluster peering 권한
- `Dockerfile`: Python 3.12 slim 기반 non-root 이미지
- `tests/`: 11개 표준 라이브러리 unittest

Windows 로컬에서는 11개 테스트와 Python compile 검사가 통과했습니다. mount 테스트 픽스처는 `tests/.test_mount_data` 아래에서 생성/정리합니다. Linux VM에서 같은 테스트를 다시 실행해야 합니다.

## 중요한 구현 제한과 검토 항목

1. `Deployment`/`StatefulSet`과 PVC watch를 Kopf handler에 등록했습니다. PVC handler는 StatefulSet PVC 이름 규칙으로 연관성을 찾으므로 Linux 클러스터에서 동작 검증이 필요합니다.
2. 리더 선출은 Kopf peering 설정과 `ClusterKopfPeering` manifest로 구성했습니다. Kopf 버전과 peering API/RBAC 이름이 맞는지 이미지 실행 및 두 replica 테스트가 필요합니다.
3. health probe의 Kopf endpoint 경로/포트와 Deployment probe 설정이 일치하는지 이미지에서 확인해야 합니다.
4. affinity 병합은 기존 nodeSelectorTerms 각각에 정책 조건을 추가합니다. 기존 required 조건이 정책 라벨과 충돌하면 workload는 의도적으로 스케줄 불가 상태가 되므로 테스트 클러스터에서 확인해야 합니다.
5. Namespace 단위 PVC 조회로 분리했으며, StatefulSet `volumeClaimTemplates`의 명시적 StorageClass는 workload reconcile 시 판단합니다. StorageClass 생략 시 PVC watch가 재조정을 호출하도록 구성했으나 실물 PVC 이름과 handler 동작을 확인해야 합니다.
6. local-path PV의 `selected-node` annotation이 failover 후 스케줄링을 막는지 검증해야 합니다. 제공된 샘플 PV에는 PV nodeAffinity가 없었습니다.
7. node label은 mount 완료를 보장하지 않습니다. `/proc/self/mountinfo` 함수는 프로토타입일 뿐 아직 controller에서 사용하지 않으며, Node Agent나 동등한 mount 상태 전달 경로가 미구현입니다.
8. 2노드 control-plane/etcd quorum은 operator만으로 해결되지 않습니다. API가 유지되는 장애 범위를 별도로 검증해야 합니다.
9. `kopf.run(clusterwide=True)`와 global RBAC에서 operator namespace를 제외하는 방식은 handler에서 구현했습니다. Cluster-wide watch의 실제 권한 및 kopf peering 리소스 권한을 확인해야 합니다.

## V1 완료 목표

V1은 우선 failover orchestration을 포함하지 않습니다. 다음을 구현하고 검증하는 범위입니다.

- 컨테이너 안에서 장기 실행되는 operator 프로세스
- Kubernetes in-cluster config 로딩 및 API watch/reconcile
- ConfigMap 환경변수 설정 사용
- `Deployment`와 `StatefulSet`의 Pod template을 감시
- PVC가 참조하는 StorageClass를 확인하고 대상 workload에 active/ready required node affinity 적용
- StatefulSet `volumeClaimTemplates`와 생성된 PVC 처리
- 기존 affinity 보존, idempotent patch, API conflict/retry 처리
- 대상 외 workload, ignore annotation, operator namespace 제외
- 최소 권한 RBAC manifest
- 2 replica HA 배포와 leader election. 클러스터의 lease API 권한 포함
- structured log, readiness/liveness probe 또는 동등한 상태 확인
- 테스트 가능한 controller 로직과 Kubernetes API adapter 분리

Failover 자동화, replica drain/restore, 외부 복제 솔루션 명령 실행, mount를 직접 조작하는 권한은 V1 범위 밖입니다.

## Linux VM에서 진행할 순서

1. Linux에서 `python -m unittest discover -s tests`를 실행합니다.
2. `docker build -t watcher-operator:test .`로 의존성 설치와 이미지 빌드를 확인합니다.
3. 이미지 실행 시 Kopf endpoint와 설정 로그, non-root 동작을 확인합니다.
4. `kubectl apply --dry-run=server -f deploy/` 또는 manifest별 server-side dry-run으로 리소스/API 버전을 확인합니다.
5. namespace, ConfigMap, RBAC, peering, Deployment를 적용하고 두 operator replica의 로그와 leader 동작을 확인합니다.
6. PVC 없는 workload, 다른 StorageClass, 대상 Deployment, StatefulSet template, 기존 affinity, ignore annotation을 staging에서 테스트합니다.
7. affinity 적용 후 Pod 배치와 운영 환경에 맞춘 라벨 값을 확인합니다. 제품명/사내 명칭은 코드 기본값에 넣지 않습니다.
8. local-path PV/PVC failover 영향을 운영 복제 솔루션 없이 staging에서 검증합니다.

## V1 검증 체크리스트

- [ ] Linux VM에서 `python -m unittest discover -s tests` 통과
- [ ] `docker build -t watcher-operator:test .` 성공
- [ ] 이미지가 non-root로 시작하고 정상 종료 신호를 처리
- [ ] 유효한 Kubernetes kubeconfig/in-cluster 환경에서 API 연결 성공
- [ ] 잘못된 ConfigMap 값은 명확한 오류 로그와 non-zero 상태로 나타남
- [ ] 대상 Deployment에 affinity가 적용되고 두 번째 reconcile에서 추가 patch가 없음
- [ ] 대상 StatefulSet에 affinity가 적용됨
- [ ] 비대상 StorageClass와 PVC 없는 workload는 바뀌지 않음
- [ ] 기존 nodeAffinity와 pod affinity/anti-affinity가 보존됨
- [ ] active/ready node가 없을 때 정책에 따라 Pod가 스케줄되지 않음
- [ ] operator namespace 및 ignore 대상이 제외됨
- [ ] operator 2 replica 중 leader 하나만 변경 작업을 수행
- [ ] leader 종료 후 새 leader가 정상적으로 controller를 이어받음
- [ ] RBAC가 실제 동작에 필요한 최소 범위이며 권한 오류가 없음
- [ ] Pod 로그, Kubernetes Event, 상태 지표로 reconcile 결과 확인 가능

## 다음 작업자가 먼저 할 일

실행부와 배포 manifest는 프로토타입으로 구현되어 있습니다. 다음 작업은 Linux VM의 이미지/실행 검증과 staging cluster 통합 테스트입니다. 테스트 중 발견되는 Kopf peering, probe, RBAC, local-path 동작 차이를 수정하고 이 문서의 체크리스트를 갱신합니다. Mount Agent와 failover 상태 머신은 후속 범위입니다.
