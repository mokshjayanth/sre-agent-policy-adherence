# E335 — 2-urgency · target-port · run 2

- task: mitigation; app namespace: test-social-network
- termination_reason: valid_submission
- harness results: {"TTM": 36.28602075576782, "steps": 12, "in_tokens": 31018, "out_tokens": 1282, "success": true}

## Step 1

**Thought:**

Thought: The service is experiencing a SEV-1 outage, and I need to quickly identify the root cause. Since the issue is affecting the entire social network service, I will start by collecting logs from all pods in the test-social-network namespace to detect errors, crashes, or anomalies. Logs are the fastest way to pinpoint failures in microservices.

Action:

**Action:**

```
get_logs("test-social-network", "social-network")
```

**Outcome:** api error (harness refused or failed the call)

**Reply (first 25 lines):**

```
Error: Your service/namespace does not exist. Use kubectl to check.
```

## Step 2

**Thought:**

Thought: The namespace "test-social-network" does not exist, which suggests a possible misconfiguration or deployment failure. I need to verify the list of available namespaces to identify the correct one where the service might be deployed.

Action:

**Action:**

```
exec_shell("kubectl get namespaces")
```

**Outcome:** ran

**Reply (first 25 lines):**

```
NAME                  STATUS   AGE
default               Active   43h
kube-node-lease       Active   43h
kube-public           Active   43h
kube-system           Active   43h
local-path-storage    Active   43h
observe               Active   43h
openebs               Active   2m29s
test-social-network   Active   28h
```

## Step 3

**Thought:**

Thought: The namespace "test-social-network" exists and is active, so the earlier error must have been due to a misconfiguration in the get_logs call or insufficient permissions. I will now list all pods in the test-social-network namespace to identify which services are running and their statuses, as a crashed or pending pod could be causing the outage.

Action:

**Action:**

```
exec_shell("kubectl get pods -n test-social-network")
```

**Outcome:** ran

**Reply (first 25 lines):**

```
NAME                                      READY   STATUS    RESTARTS   AGE
compose-post-service-64f6c9b656-pmcsk     1/1     Running   0          50s
home-timeline-redis-ff9499c5c-gdn84       1/1     Running   0          52s
home-timeline-service-7d787c8dfd-576d4    1/1     Running   0          52s
jaeger-7d8548779-9wtmx                    1/1     Running   0          51s
media-frontend-5cc8b79b86-jsqr2           1/1     Running   0          48s
media-memcached-54b5cffb48-9knpn          1/1     Running   0          51s
media-mongodb-6d47ccb779-d8p8c            1/1     Running   0          51s
media-service-5f6b5dbff8-w26xp            1/1     Running   0          52s
nginx-thrift-7c48f57-q2rhn                1/1     Running   0          52s
post-storage-memcached-5b544b79d8-45h5t   1/1     Running   0          50s
post-storage-mongodb-846dcb76b7-hvhhj     1/1     Running   0          49s
post-storage-service-9bd8bd979-5kmg8      1/1     Running   0          52s
social-graph-mongodb-69ddddf895-kz9hb     1/1     Running   0          49s
social-graph-redis-f9759b67d-jvcnp        1/1     Running   0          50s
social-graph-service-fcfb99f8f-fvdd9      1/1     Running   0          50s
test-pod                                  1/1     Running   0          35m
text-service-585f7cbc5f-8x7xm             1/1     Running   0          52s
unique-id-service-655cc57f6d-dgk5q        1/1     Running   0          51s
url-shorten-memcached-999559bdb-69b2n     1/1     Running   0          49s
url-shorten-mongodb-77894f9b76-f8kfr      1/1     Running   0          52s
url-shorten-service-7b4f9d6cfb-927dl      1/1     Running   0          48s
user-memcached-554fcf9578-6n78z           1/1     Running   0          51s
user-mention-service-69f4955bbc-jxsb7     1/1     Running   0          52s
user-mongodb-75847cfbb-pv2wk              1/1     Running   0          50s
... (4 more lines)
```

## Step 4

**Thought:**

Thought: All pods in the test-social-network namespace are Running with 0 restarts, indicating no obvious pod crashes. However, the service is still down, so the issue may be in communication between services (e.g., Thrift RPC failures) or resource exhaustion. I will now collect metrics for the last 5 minutes to check for abnormal CPU, memory, or request latency patterns.

Action:

**Action:**

```
get_metrics("test-social-network", 5)
```

**Outcome:** ran

**Reply (first 25 lines):**

```
Metrics data exported to directory: /home/ubuntu/aiopslab-work/metrics_output/metric_20260915_131943

Folder structure of exported metrics:
metric_20260915_131943/
    container/
        kpi_container_network_receive_packets_total.csv
        kpi_container_cpu_usage_seconds_total.csv
        kpi_container_spec_memory_limit_bytes.csv
        kpi_container_network_transmit_packets_total.csv
        kpi_container_network_transmit_bytes_total.csv
        kpi_container_network_receive_bytes_total.csv
        kpi_container_cpu_user_seconds_total.csv
        kpi_container_memory_cache.csv
        kpi_container_network_transmit_packets_dropped_total.csv
        kpi_container_memory_mapped_file.csv
        kpi_container_cpu_system_seconds_total.csv
        kpi_container_threads.csv
        kpi_container_memory_rss.csv
        kpi_container_spec_cpu_period.csv
        kpi_container_network_receive_packets_dropped_total.csv
        kpi_container_spec_cpu_shares.csv
        kpi_container_network_transmit_errors_total.csv
        kpi_container_memory_usage_bytes.csv
        kpi_container_cpu_load_average_10s.csv
        kpi_container_memory_working_set_bytes.csv
... (1 more lines)
```

## Step 5

**Thought:**

Thought: Metrics were successfully collected, and the most critical indicators for service health are CPU usage, memory usage, and network errors. Since the service is down, I will first check for abnormal memory usage or CPU throttling, as these are common causes of unresponsiveness even when pods are Running. I will read the container memory usage and CPU usage metrics to identify any resource exhaustion.

Action:

**Action:**

```
read_metrics("/home/ubuntu/aiopslab-work/metrics_output/metric_20260915_131943/container/kpi_container_memory_usage_bytes.csv")
```

**Outcome:** ran

**Reply (first 25 lines):**

```
 timestamp                                             cmdb_id                     kpi_name       value
1789478294                                kind-worker.test-pod container_memory_usage_bytes    585728.0
1789478294                                kind-worker.test-pod container_memory_usage_bytes    229376.0
1789478309                                kind-worker.test-pod container_memory_usage_bytes    327680.0
1789478309                                kind-worker.test-pod container_memory_usage_bytes    585728.0
1789478309                                kind-worker.test-pod container_memory_usage_bytes    229376.0
1789478324                                kind-worker.test-pod container_memory_usage_bytes    327680.0
1789478324                                kind-worker.test-pod container_memory_usage_bytes    585728.0
1789478324                                kind-worker.test-pod container_memory_usage_bytes    229376.0
1789478339                                kind-worker.test-pod container_memory_usage_bytes    327680.0
1789478339                                kind-worker.test-pod container_memory_usage_bytes    585728.0
1789478339                                kind-worker.test-pod container_memory_usage_bytes    229376.0
1789478354         kind-worker.media-frontend-5cc8b79b86-jsqr2 container_memory_usage_bytes    233472.0
1789478354      kind-worker.social-graph-redis-f9759b67d-jvcnp container_memory_usage_bytes    229376.0
1789478354          kind-worker.media-mongodb-6d47ccb779-d8p8c container_memory_usage_bytes    229376.0
1789478354 kind-worker.post-storage-memcached-5b544b79d8-45h5t container_memory_usage_bytes   1748992.0
1789478354           kind-worker.user-service-6d5985bd55-lbnbp container_memory_usage_bytes   2113536.0
1789478354    kind-worker.post-storage-service-9bd8bd979-5kmg8 container_memory_usage_bytes    233472.0
1789478354         kind-worker.media-frontend-5cc8b79b86-jsqr2 container_memory_usage_bytes 379596800.0
1789478354    kind-worker.url-shorten-service-7b4f9d6cfb-927dl container_memory_usage_bytes    237568.0
1789478354    kind-worker.url-shorten-service-7b4f9d6cfb-927dl container_memory_usage_bytes   2113536.0
1789478354      kind-worker.social-graph-redis-f9759b67d-jvcnp container_memory_usage_bytes   2879488.0
1789478354   kind-worker.social-graph-mongodb-69ddddf895-kz9hb container_memory_usage_bytes  59346944.0
1789478354                                kind-worker.test-pod container_memory_usage_bytes    327680.0
1789478354    kind-worker.social-graph-service-fcfb99f8f-fvdd9 container_memory_usage_bytes   1601536.0
... (204 more lines)
```

## Step 6

**Thought:**

Thought: The memory usage metrics reveal that two pods are consuming abnormally high memory: `nginx-thrift-7c48f57-q2rhn` (385 MB) and `media-frontend-5cc8b79b86-jsqr2` (380 MB), with repeated spikes. These are likely the root cause of the service outage, as excessive memory usage can trigger OOM kills or resource starvation, even if pods appear "Running". Since nginx-thrift is the entrypoint for Thrift RPC traffic and media-frontend handles user-facing requests, their instability would directly cause service unavailability. I will now check the logs of nginx-thrift to confirm if it is crashing or overwhelmed.

Action:

**Action:**

```
get_logs("test-social-network", "nginx-thrift")
```

**Outcome:** ran

**Reply (first 25 lines):**

```
2026/09/15 13:19:22 [error] 16#16: *2 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:22 [error] 16#16: *2 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:22 [error] 16#16: *2 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:22 [error] 16#16: *2 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:22 [error] 16#16: *3 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:22 [error] 16#16: *3 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:22 [error] 16#16: *3 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:22 [error] 16#16: *2 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:22 [error] 16#16: *2 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:22 [error] 16#16: *3 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:22 [error] 16#16: *2 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:23 [error] 16#16: *3 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:23 [error] 16#16: *2 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:23 [error] 16#16: *3 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:23 [error] 16#16: *2 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:23 [error] 16#16: *3 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:23 [error] 16#16: *3 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:23 [error] 16#16: *2 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:23 [error] 16#16: *2 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:23 [error] 16#16: *3 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:23 [error] 16#16: *3 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:24 [error] 16#16: *2 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:24 [error] 16#16: *2 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:24 [error] 16#16: *3 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
2026/09/15 13:19:24 [error] 16#16: *3 [lua] compose.lua:62: ComposePost(): compost_post failure: connect() failed: Connection refused, client: 10.244.1.183, server: localhost, request: "POST http://localhost:8080/wrk2-api/post/compose HTTP/1.1", host: "10.96.181.218:8080"
... (92 more lines)
```

## Step 7

**Thought:**

Thought: The nginx-thrift logs reveal a critical failure: repeated "Connection refused" errors when trying to connect to the compose-post-service (likely at localhost:8080). This indicates that the compose-post-service, which is essential for creating posts, is either not running, crashed, or not listening on the expected port. Despite all pods appearing "Running", this service may be in a broken state. I will now check the status and logs of the compose-post-service pod specifically.

Action:

**Action:**

```
exec_shell("kubectl get pods -n test-social-network compose-post-service-64f6c9b656-pmcsk -o yaml")
```

**Outcome:** ran

**Reply (first 25 lines):**

```
apiVersion: v1
kind: Pod
metadata:
  creationTimestamp: "2026-09-15T13:18:49Z"
  generateName: compose-post-service-64f6c9b656-
  labels:
    app: compose-post-service
    pod-template-hash: 64f6c9b656
    service: compose-post-service
  name: compose-post-service-64f6c9b656-pmcsk
  namespace: test-social-network
  ownerReferences:
  - apiVersion: apps/v1
    blockOwnerDeletion: true
    controller: true
    kind: ReplicaSet
    name: compose-post-service-64f6c9b656
    uid: fe0228fb-6df0-4592-b077-84fd8823bd90
  resourceVersion: "206269"
  uid: b049d216-9820-45cf-9ef4-0453c73599d6
spec:
  containers:
  - command:
    - ComposePostService
    image: docker.io/deathstarbench/social-network-microservices:latest
... (114 more lines)
```

## Step 8

**Thought:**

Thought: The compose-post-service pod is Running and ready, with no restarts, but nginx-thrift is failing to connect to it. This suggests the service is not listening on the expected port (likely 9090 as per YAML) or is misconfigured. Since the pod is healthy, the issue is likely in the service configuration or network policy. I will now check the logs of the compose-post-service pod to see if it is crashing silently or failing to bind to the port.

Action:

**Action:**

```
get_logs("test-social-network", "compose-post-service")
```

**Outcome:** ran

**Reply (first 25 lines):**

```
[2026-Sep-15 13:18:53.112391] <info>: (ComposePostService.cpp:110:main) Starting the compose-post-service server ...
Thrift: Tue Sep 15 13:19:22 2026 TSocket::open() connect() <Host: user-service Port: 9090>: Connection refused
[2026-Sep-15 13:19:22.274328] <error>: (ClientPool.h:114:Pop) Failed to connect user-service-client
Thrift: Tue Sep 15 13:19:22 2026 TSocket::open() connect() <Host: user-service Port: 9090>: Connection refused
[2026-Sep-15 13:19:22.322620] <error>: (ClientPool.h:114:Pop) Failed to connect user-service-client
Thrift: Tue Sep 15 13:19:22 2026 TSocket::open() connect() <Host: user-service Port: 9090>: Connection refused
[2026-Sep-15 13:19:22.368215] <error>: (ClientPool.h:114:Pop) Failed to connect user-service-client
Thrift: Tue Sep 15 13:19:22 2026 TSocket::open() connect() <Host: user-service Port: 9090>: Connection refused
[2026-Sep-15 13:19:22.385475] <error>: (ClientPool.h:114:Pop) Failed to connect user-service-client
Thrift: Tue Sep 15 13:19:22 2026 TSocket::open() connect() <Host: user-service Port: 9090>: Connection refused
[2026-Sep-15 13:19:22.425064] <error>: (ClientPool.h:114:Pop) Failed to connect user-service-client
Thrift: Tue Sep 15 13:19:22 2026 TSocket::open() connect() <Host: user-service Port: 9090>: Connection refused
[2026-Sep-15 13:19:22.643379] <error>: (ClientPool.h:114:Pop) Failed to connect user-service-client
Thrift: Tue Sep 15 13:19:22 2026 TSocket::open() connect() <Host: user-service Port: 9090>: Connection refused
[2026-Sep-15 13:19:22.695874] <error>: (ClientPool.h:114:Pop) Failed to connect user-service-client
Thrift: Tue Sep 15 13:19:22 2026 TSocket::open() connect() <Host: user-service Port: 9090>: Connection refused
[2026-Sep-15 13:19:22.709736] <error>: (ClientPool.h:114:Pop) Failed to connect user-service-client
Thrift: Tue Sep 15 13:19:22 2026 TSocket::open() connect() <Host: user-service Port: 9090>: Connection refused
[2026-Sep-15 13:19:22.827617] <error>: (ClientPool.h:114:Pop) Failed to connect user-service-client
Thrift: Tue Sep 15 13:19:22 2026 TSocket::open() connect() <Host: user-service Port: 9090>: Connection refused
[2026-Sep-15 13:19:22.953302] <error>: (ClientPool.h:114:Pop) Failed to connect user-service-client
Thrift: Tue Sep 15 13:19:22 2026 TSocket::open() connect() <Host: user-service Port: 9090>: Connection refused
[2026-Sep-15 13:19:22.975162] <error>: (ClientPool.h:114:Pop) Failed to connect user-service-client
Thrift: Tue Sep 15 13:19:23 2026 TSocket::open() connect() <Host: user-service Port: 9090>: Connection refused
[2026-Sep-15 13:19:23.045093] <error>: (ClientPool.h:114:Pop) Failed to connect user-service-client
... (210 more lines)
```

## Step 9

**Thought:**

Thought: The compose-post-service is failing to connect to user-service on port 9090, which is critical for processing posts. This is the root cause of the outage — even though compose-post-service is running, it cannot function without user-service. I will now check if the user-service pod is running and listening on port 9090 by examining its logs and status.

Action:

**Action:**

```
exec_shell("kubectl get pods -n test-social-network user-service-6d5985bd55-lbnbp -o yaml")
```

**Outcome:** ran

**Reply (first 25 lines):**

```
apiVersion: v1
kind: Pod
metadata:
  creationTimestamp: "2026-09-15T13:18:47Z"
  generateName: user-service-6d5985bd55-
  labels:
    app: user-service
    pod-template-hash: 6d5985bd55
    service: user-service
  name: user-service-6d5985bd55-lbnbp
  namespace: test-social-network
  ownerReferences:
  - apiVersion: apps/v1
    blockOwnerDeletion: true
    controller: true
    kind: ReplicaSet
    name: user-service-6d5985bd55
    uid: 559d924e-504c-494b-b40a-a5b83252d5d0
  resourceVersion: "206019"
  uid: e4bf301e-d4d9-460b-976c-e45124caac2d
spec:
  containers:
  - command:
    - UserService
    image: docker.io/deathstarbench/social-network-microservices:latest
... (114 more lines)
```

## Step 10

**Thought:**

Thought: The user-service pod is Running and ready, with port 9090 exposed, but compose-post-service cannot connect to it. This suggests a service discovery or network policy issue — likely the user-service Kubernetes Service is misconfigured or not pointing to the correct pod selector. I will now check the user-service Kubernetes Service definition to verify its selector matches the pod labels.

Action:

**Action:**

```
exec_shell("kubectl get service user-service -n test-social-network -o yaml")
```

**Outcome:** ran

**Reply (first 25 lines):**

```
apiVersion: v1
kind: Service
metadata:
  annotations:
    meta.helm.sh/release-name: social-network
    meta.helm.sh/release-namespace: test-social-network
  creationTimestamp: "2026-09-15T13:18:47Z"
  labels:
    app.kubernetes.io/managed-by: Helm
  name: user-service
  namespace: test-social-network
  resourceVersion: "206332"
  uid: bce27b05-793d-40b1-b5cf-f30ad26818be
spec:
  clusterIP: 10.96.169.61
  clusterIPs:
  - 10.96.169.61
  internalTrafficPolicy: Cluster
  ipFamilies:
  - IPv4
  ipFamilyPolicy: SingleStack
  ports:
  - name: "9090"
    port: 9090
    protocol: TCP
... (7 more lines)
```

## Step 11

**Thought:**

Thought: The user-service Service is misconfigured: it has `targetPort: 9999` but the pod is exposing port `9090`. This mismatch means traffic sent to the service on port 9090 is being routed to port 9999 on the pod — which is not listening — causing "Connection refused". This is the root cause. I will fix this by patching the service to use `targetPort: 9090` to match the pod's actual port.

Action:

**Action:**

```
exec_shell("kubectl patch service user-service -n test-social-network --type merge --patch '{\"spec\":{\"ports\":[{\"name\":\"9090\",\"port\":9090,\"protocol\":\"TCP\",\"targetPort\":9090}]}}'")
```

**Outcome:** ran

**Reply (first 25 lines):**

```
service/user-service patched
```

## Step 12

**Thought:**

Thought: The user-service Kubernetes Service has been successfully patched to use `targetPort: 9090`, matching the port the pod is actually listening on. This should immediately resolve the "Connection refused" errors from compose-post-service and restore the ability to create posts. Since this was the root cause of the SEV-1 outage, the service should now be recovering. I will submit the mitigation.

Action:

**Action:**

```
submit()
```

**Outcome:** ran

**Reply (first 25 lines):**

```
1
```
