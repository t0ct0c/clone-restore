# Kubernetes Migration - Integration Overview

This document provides a quick reference to all documentation and specs for the Kubernetes migration project.

## Document Hierarchy

```
📁 Repository Root
├── 📄 KUBERNETES_DEPLOYMENT_PLAN.md      ← Strategic migration plan
├── 📄 KUBERNETES_IMPLEMENTATION_GUIDE.md ← Step-by-step implementation
├── 📄 OPERATIONAL_MEMORY.md              ← Current EC2 system docs
│
└── 📁 openspec/changes/kubernetes-migration/
    ├── 📄 proposal.md                    ← Why and what (business case)
    ├── 📄 design.md                      ← Architecture and components
    ├── 📄 tasks.md                       ← Implementation tasks
    ├── 📄 INTEGRATION.md                 ← This file
    │
    └── 📁 specs/
        ├── 📁 kubernetes-infrastructure/ ← EKS cluster spec
        │   └── spec.md
        ├── 📁 kro-orchestration/        ← KRO ResourceGroups spec
        │   └── spec.md
        ├── 📁 ack-integration/          ← ACK RDS/IAM spec
        │   └── spec.md
        ├── 📁 gitops-cicd/              ← Argo CD spec
        │   └── spec.md
        └── 📁 wp-k8s-service/           ← Management service spec
            └── spec.md
```

## Quick Links

### Strategic Documents
| Document | Purpose | Audience |
|----------|---------|----------|
| [KUBERNETES_DEPLOYMENT_PLAN.md](../../KUBERNETES_DEPLOYMENT_PLAN.md) | High-level migration strategy, phases, risk assessment | Stakeholders, Tech Leads |
| [KUBERNETES_IMPLEMENTATION_GUIDE.md](../../KUBERNETES_IMPLEMENTATION_GUIDE.md) | Step-by-step implementation with code samples | Developers |
| [OPERATIONAL_MEMORY.md](../../OPERATIONAL_MEMORY.md) | Current EC2 system documentation | DevOps, Troubleshooting |

### OpenSpec Documents
| Document | Purpose | Audience |
|----------|---------|----------|
| [proposal.md](./proposal.md) | Business case, why migrate, what changes | Decision makers |
| [design.md](./design.md) | Architecture, component mapping, technology choices | Architects, Developers |
| [tasks.md](./tasks.md) | Implementation checklist with estimates | Project managers, Developers |

### Technical Specs
| Spec | Purpose | Key Requirements |
|------|---------|------------------|
| [kubernetes-infrastructure](./specs/kubernetes-infrastructure/spec.md) | EKS cluster, VPC, IRSA | REQ-K8S-001 to REQ-K8S-007 |
| [kro-orchestration](./specs/kro-orchestration/spec.md) | KRO ResourceGroups | WordPress clone CRD |
| [ack-integration](./specs/ack-integration/spec.md) | ACK RDS controller | Database provisioning |
| [gitops-cicd](./specs/gitops-cicd/spec.md) | Argo CD, GitHub Actions | Deployment automation |
| [wp-k8s-service](./specs/wp-k8s-service/spec.md) | Management service | REQ-WPK8S-001 to REQ-WPK8S-006 |

## Migration Timeline

```
Week 1: EKS Foundation
├── Task 1.1: Create EKS Cluster (Terraform)
├── Task 1.2: Install ACK Controllers
├── Task 1.3: Install KRO
├── Task 1.4: Install Argo CD
├── Task 1.5: Install Cluster Autoscaler
└── Task 1.6: Install AWS Load Balancer Controller

Week 2: KRO ResourceGroups
├── Task 2.1: Create RDS Prerequisites
├── Task 2.2: Create WordPress Clone ResourceGroup
├── Task 2.3: Test Manual Clone Creation
├── Task 2.4: Test TTL Cleanup
└── Task 2.5: Create Shared RDS for Staging

Week 3: wp-k8s-service
├── Task 3.1: Create KRO Provisioner
├── Task 3.2: Create FastAPI Service
├── Task 3.3: Create Dockerfile
├── Task 3.4: Push Image to ECR
├── Task 3.5: Create Kubernetes Manifests
└── Task 3.6: Test End-to-End Clone Creation

Week 4: GitOps & Observability
├── Task 4.1: Create Kustomize Overlays
├── Task 4.2: Create Argo CD Applications
├── Task 4.3: Create GitHub Actions Workflow
├── Task 4.4: Test GitOps Workflow
└── Task 5.1: Deploy OpenTelemetry Collector

Week 5: Migration & Cutover
├── Task 6.1: Validation Checklist
├── Task 6.2: DNS Cutover
├── Task 6.3: Monitor for 48 Hours
└── Task 6.4: Decommission EC2 Infrastructure
```

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| EKS Version | 1.35 | Latest stable, long-term support |
| Orchestration | KRO | Reduces provisioning code by 80% |
| Database | Shared RDS (staging), Per-clone RDS (production) | Cost optimization |
| GitOps | Argo CD | Industry standard, automatic sync |
| CI/CD | GitHub Actions | Already using GitHub |
| Observability | OpenTelemetry + CloudWatch | AWS native, existing integration |

## Success Metrics

| Metric | Target | Validation |
|--------|--------|------------|
| Clone creation time | < 5 minutes | Timer in integration tests |
| TTL cleanup | 100% automatic | No orphaned resources |
| Path-based routing | Works via Ingress | ALB rules created automatically |
| Browser automation | Works in container | SiteGround test passes |
| Auto-scaling | HPA + CA functional | Load test triggers scale-up |
| GitOps deployment | Automatic from Git | Push triggers deploy |
| Monthly cost | < $250 | AWS Cost Explorer |

## Contacts

| Role | Responsibility |
|------|---------------|
| Project Lead | Overall migration ownership |
| DevOps Engineer | EKS infrastructure, Terraform |
| Backend Developer | wp-k8s-service, KRO provisioner |
| QA Engineer | Testing, validation checklist |

## Getting Started

1. **Read the strategic plan**: Start with [KUBERNETES_DEPLOYMENT_PLAN.md](../../KUBERNETES_DEPLOYMENT_PLAN.md)
2. **Understand the business case**: Review [proposal.md](./proposal.md)
3. **Review architecture**: Study [design.md](./design.md)
4. **Start implementation**: Follow [KUBERNETES_IMPLEMENTATION_GUIDE.md](../../KUBERNETES_IMPLEMENTATION_GUIDE.md)
5. **Track progress**: Use [tasks.md](./tasks.md) checklist

## Rollback Plan

If migration fails at any point:
1. **DNS Rollback**: Switch back to EC2 ALB (< 5 minutes)
2. **EC2 System**: Remains running throughout migration
3. **Data Safety**: RDS databases independent of compute layer
4. **Cost Control**: Delete EKS cluster to stop $73/mo control plane cost

---

**Last Updated**: 2026-02-08
**Branch**: feat/kubernetes
