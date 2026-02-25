# Migration Documentation Overview

This directory contains comprehensive documentation to facilitate the refactoring of the WordPress Clone & Restore system from the current EC2-based architecture to Kubernetes.

## Documents

### 1. FEAT_RESTORE_ARCHITECTURE.md
**Purpose**: Complete technical documentation of the current implementation on the `feat/restore` branch.

**Contents**:
- System overview and capabilities
- Detailed architecture diagrams
- Component breakdown (FastAPI, WordPress, MySQL, ALB, Nginx)
- Infrastructure stack (AWS resources, Docker containers)
- Core workflows (/clone and /restore endpoints)
- API endpoint specifications
- Code structure and key files
- Data flow (export/import process)
- Deployment and operational procedures
- Strengths and limitations

**Use this document to**:
- Understand how the current system works
- Reference existing workflows when designing Kubernetes equivalents
- Identify components that need to be migrated or replaced
- Compare trade-offs between current and future architectures

### 2. KUBERNETES_MIGRATION_COMPARISON.md
**Purpose**: Side-by-side comparison between current (feat/restore) and target (Kubernetes) architectures with detailed migration guidance.

**Contents**:
- Executive summary (current vs target state)
- Component mapping (EC2 → Kubernetes equivalents)
- Workflow comparisons (before/after)
- Infrastructure changes (networking, Terraform)
- Code migration strategy (phased approach)
- Critical design decisions (with recommendations)
- Migration roadmap (6 phases)
- Code examples (k8s_provisioner.py, KRO ResourceGroups)

**Use this document to**:
- Plan the refactoring approach
- Make informed design decisions
- Understand what code needs to change
- See concrete examples of Kubernetes implementations
- Track migration progress

## How to Use These Documents

### For Planning
1. Read `FEAT_RESTORE_ARCHITECTURE.md` to understand the current system deeply
2. Read `KUBERNETES_MIGRATION_COMPARISON.md` Section 2 (Component Mapping) to see how each piece translates to Kubernetes
3. Review Section 6 (Critical Design Decisions) to make key architectural choices
4. Use Section 7 (Migration Roadmap) to create a work breakdown

### For Implementation
1. Reference `KUBERNETES_MIGRATION_COMPARISON.md` Section 5 (Code Migration Strategy) for step-by-step guidance
2. Use Section 8 (Code Examples) as templates for Kubernetes implementations
3. Refer back to `FEAT_RESTORE_ARCHITECTURE.md` for details on current behavior that must be preserved

### For Comparison
1. Use the "Before vs After" sections in `KUBERNETES_MIGRATION_COMPARISON.md`
2. Compare infrastructure diagrams
3. Review workflow sequence diagrams side-by-side

## Key Insights

### What's Changing
- ❌ **Removing**: SSH operations, paramiko, manual port allocation, Nginx configs on EC2, ALB API calls
- ➕ **Adding**: Kubernetes API calls, KRO ResourceGroups, Ingress resources, ACK RDS controller
- 🔄 **Replacing**: ec2_provisioner.py → k8s_provisioner.py

### What's Staying
- ✅ **Keeping**: Browser automation (Playwright + Camoufox), WordPress custom plugin, export/import logic, selective preservation, Loki/Tempo observability

### Critical Path
1. ✅ EKS cluster + Karpenter + KEDA (DONE)
2. ⏳ Install ACK RDS + KRO + Argo CD + AWS Load Balancer Controller
3. ⏳ Deploy wp-k8s-service (FastAPI) to Kubernetes
4. ⏳ Create KRO ResourceGroup for WordPress clones
5. ⏳ Implement k8s_provisioner.py (core refactoring)
6. ⏳ Test /clone and /restore endpoints end-to-end

## Quick Links

### Current System (feat/restore)
- FastAPI Code: `custom-wp-migrator-poc/wp-setup-service/app/main.py`
- EC2 Provisioner: `custom-wp-migrator-poc/wp-setup-service/app/ec2_provisioner.py`
- WordPress Plugin: `custom-wp-migrator-poc/wordpress-target-image/plugin/`
- Infrastructure: `custom-wp-migrator-poc/infra/wp-targets/`

### Target System (feat/kubernetes)
- EKS Cluster: `kubernetes/bootstrap/terraform/`
- Kubernetes Tasks: `openspec/changes/kubernetes-migration/tasks.md`
- Architecture: `openspec/changes/kubernetes-migration/design.md`

## Questions to Answer

As you review these documents, consider:

1. **Database Strategy**: Shared RDS instance vs. RDS per clone?
2. **Provisioning Method**: KRO ResourceGroup vs. Helm Chart vs. Manual resources?
3. **Storage**: EmptyDir vs. S3 + PVC for WordPress uploads?
4. **TTL Cleanup**: CronJob per clone vs. custom controller?
5. **Ingress**: One Ingress per clone vs. single shared Ingress?

All of these have recommendations in `KUBERNETES_MIGRATION_COMPARISON.md`, but you should validate them against your requirements.

## Next Steps

1. ✅ Review both documents thoroughly
2. ⏳ Create comparison document for stakeholders (if needed)
3. ⏳ Validate design decisions with team
4. ⏳ Begin Phase 2 of migration roadmap (Core Service)
5. ⏳ Implement k8s_provisioner.py
6. ⏳ Test end-to-end workflows

## Feedback

These documents were generated on 2026-02-06 based on the current state of the `feat/restore` and `feat/kubernetes` branches. As the implementation progresses, update these documents to reflect actual decisions and learnings.

---

**Generated**: 2026-02-06
**Author**: Claude
**Branches**: feat/restore (source) + feat/kubernetes (target)
