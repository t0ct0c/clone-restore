# Karpenter Configuration
# Advanced node autoscaling - provisions nodes in ~30 seconds based on pod requirements

# IAM role for Karpenter controller
module "karpenter_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name = "${var.cluster_name}-karpenter-controller"

  attach_karpenter_controller_policy = true
  karpenter_sqs_queue_arn           = aws_sqs_queue.karpenter.arn

  karpenter_controller_cluster_name       = module.eks.cluster_name
  karpenter_controller_node_iam_role_arns = [module.eks.eks_managed_node_groups["ng1"].iam_role_arn]

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["karpenter:karpenter"]
    }
  }

  tags = {
    Name = "${var.cluster_name}-karpenter-controller"
  }
}

# IAM instance profile for Karpenter nodes
resource "aws_iam_instance_profile" "karpenter_node" {
  name = "${var.cluster_name}-karpenter-node"
  role = aws_iam_role.karpenter_node.name
}

resource "aws_iam_role" "karpenter_node" {
  name = "${var.cluster_name}-karpenter-node"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

# Attach required policies for Karpenter nodes
resource "aws_iam_role_policy_attachment" "karpenter_node_policies" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
    "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  ])

  policy_arn = each.value
  role       = aws_iam_role.karpenter_node.name
}

# SQS queue for Karpenter interruption handling (spot instances)
resource "aws_sqs_queue" "karpenter" {
  name                      = "${var.cluster_name}-karpenter"
  message_retention_seconds = 300
  sqs_managed_sse_enabled   = true

  tags = {
    Name = "${var.cluster_name}-karpenter"
  }
}

resource "aws_sqs_queue_policy" "karpenter" {
  queue_url = aws_sqs_queue.karpenter.url

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = [
            "events.amazonaws.com",
            "sqs.amazonaws.com"
          ]
        }
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.karpenter.arn
      }
    ]
  })
}

# EventBridge rules for spot interruptions
resource "aws_cloudwatch_event_rule" "karpenter_spot_interruption" {
  name        = "${var.cluster_name}-karpenter-spot-interruption"
  description = "Karpenter spot instance interruption warning"

  event_pattern = jsonencode({
    source      = ["aws.ec2"]
    detail-type = ["EC2 Spot Instance Interruption Warning"]
  })
}

resource "aws_cloudwatch_event_target" "karpenter_spot_interruption" {
  rule      = aws_cloudwatch_event_rule.karpenter_spot_interruption.name
  target_id = "KarpenterInterruptionQueueTarget"
  arn       = aws_sqs_queue.karpenter.arn
}

# Install Karpenter via Helm
resource "helm_release" "karpenter" {
  namespace        = "karpenter"
  create_namespace = true

  name       = "karpenter"
  repository = "oci://public.ecr.aws/karpenter"
  chart      = "karpenter"
  version    = "1.8.6"

  values = [
    <<-EOT
    settings:
      clusterName: ${module.eks.cluster_name}
      clusterEndpoint: ${module.eks.cluster_endpoint}
      interruptionQueue: ${aws_sqs_queue.karpenter.name}

    serviceAccount:
      annotations:
        eks.amazonaws.com/role-arn: ${module.karpenter_irsa.iam_role_arn}

    controller:
      resources:
        requests:
          cpu: 100m
          memory: 128Mi
        limits:
          cpu: 500m
          memory: 512Mi
    EOT
  ]

  depends_on = [
    module.eks,
    module.karpenter_irsa
  ]

  timeout = 900  # 15 minutes timeout for Karpenter installation
}

# Karpenter NodePool (replaces NodeClass in v1.0+)
resource "kubectl_manifest" "karpenter_node_pool" {
  yaml_body = <<-YAML
    apiVersion: karpenter.sh/v1
    kind: NodePool
    metadata:
      name: general-purpose
    spec:
      template:
        metadata:
          labels:
            karpenter.sh/capacity-type: spot
        spec:
          nodeClassRef:
            group: karpenter.k8s.aws
            kind: EC2NodeClass
            name: default
          requirements:
            - key: karpenter.sh/capacity-type
              operator: In
              values: ["spot"]  # Prefer spot for cost savings; add "on-demand" if needed
            - key: kubernetes.io/arch
              operator: In
              values: ["amd64"]
            - key: karpenter.k8s.aws/instance-category
              operator: In
              values: ["c", "m", "r", "t"]
            - key: karpenter.k8s.aws/instance-generation
              operator: Gt
              values: ["2"]
      limits:
        cpu: "100"
        memory: "200Gi"
      disruption:
        consolidationPolicy: WhenEmpty
        consolidateAfter: 30s
  YAML

  depends_on = [helm_release.karpenter]
}

# Karpenter EC2NodeClass
resource "kubectl_manifest" "karpenter_node_class" {
  yaml_body = <<-YAML
    apiVersion: karpenter.k8s.aws/v1
    kind: EC2NodeClass
    metadata:
      name: default
    spec:
      amiFamily: AL2
      amiSelectorTerms:
        - alias: al2@latest
      instanceProfile: ${aws_iam_instance_profile.karpenter_node.name}
      subnetSelectorTerms:
        - tags:
            karpenter.sh/discovery: ${var.cluster_name}
      securityGroupSelectorTerms:
        - tags:
            karpenter.sh/discovery: ${var.cluster_name}
      tags:
        Name: ${var.cluster_name}-karpenter-node
        karpenter.sh/discovery: ${var.cluster_name}
  YAML

  depends_on = [helm_release.karpenter]
}
