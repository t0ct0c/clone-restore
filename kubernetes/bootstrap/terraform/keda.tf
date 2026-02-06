# KEDA Configuration
# Kubernetes Event-Driven Autoscaling - scale pods based on events, metrics, queues, etc.

# Namespace for KEDA
resource "kubernetes_namespace" "keda" {
  metadata {
    name = "keda"
    labels = {
      name       = "keda"
      managed-by = "terraform"
    }
  }

  depends_on = [module.eks]
}

# Install KEDA via Helm
resource "helm_release" "keda" {
  namespace = kubernetes_namespace.keda.metadata[0].name

  name       = "keda"
  repository = "https://kedacore.github.io/charts"
  chart      = "keda"
  version    = "2.14.0"

  values = [
    <<-EOT
    # KEDA Operator configuration
    operator:
      name: keda-operator
      replicaCount: 1
      resources:
        requests:
          cpu: 100m
          memory: 128Mi
        limits:
          cpu: 500m
          memory: 512Mi

    # KEDA Metrics Server
    metricsServer:
      replicaCount: 1
      resources:
        requests:
          cpu: 100m
          memory: 128Mi
        limits:
          cpu: 500m
          memory: 512Mi

    # KEDA Webhooks
    webhooks:
      enabled: true
      replicaCount: 1
      resources:
        requests:
          cpu: 50m
          memory: 64Mi
        limits:
          cpu: 200m
          memory: 256Mi

    # Service account
    serviceAccount:
      create: true
      name: keda-operator
      annotations: {}

    # Prometheus metrics
    prometheus:
      metricServer:
        enabled: true
        port: 9022
        portName: metrics
      operator:
        enabled: true
        port: 8080
        portName: metrics
      webhooks:
        enabled: true
        port: 8080
        portName: metrics
    EOT
  ]

  depends_on = [module.eks]
}

# Example ScaledObject for wp-k8s-service
# NOTE: This will be created in Phase 3 when wp-k8s-service is deployed
# For now, this serves as documentation for how to use KEDA
#
# Example usage:
# apiVersion: keda.sh/v1alpha1
# kind: ScaledObject
# metadata:
#   name: wp-k8s-service-scaler
#   namespace: wordpress-production
# spec:
#   scaleTargetRef:
#     name: wp-k8s-service
#   minReplicaCount: 1
#   maxReplicaCount: 10
#   triggers:
#     - type: cpu
#       metricType: Utilization
#       metadata:
#         value: "70"
