"""
TTL Cleaner - Returns warm pool pods to pool instead of deleting them
"""

import os
import time
from datetime import datetime
from kubernetes import client, config
from loguru import logger

from .warm_pool_controller import WarmPoolController


def cleanup_expired_clones():
    """Clean up expired clones, returning warm pool pods to pool"""

    config.load_incluster_config()
    apps_api = client.AppsV1Api()
    core_api = client.CoreV1Api()
    networking_api = client.NetworkingV1Api()

    namespace = os.getenv("KUBERNETES_NAMESPACE", "wordpress-staging")
    now = int(time.time())
    deleted_count = 0
    returned_count = 0

    logger.info(f"Starting TTL cleanup at {datetime.now()}")
    logger.info(f"Current timestamp: {now}")

    # Get warm pool controller for returning pods
    warm_pool = WarmPoolController(namespace=namespace)

    deployments = apps_api.list_namespaced_deployment(
        namespace=namespace, label_selector="ttl-expires-at"
    )

    for deployment in deployments.items:
        name = deployment.metadata.name
        ttl_label = deployment.metadata.labels.get("ttl-expires-at")

        if not ttl_label:
            continue

        try:
            ttl_timestamp = int(ttl_label)
        except ValueError:
            logger.warning(f"Invalid TTL for {name}: {ttl_label}")
            continue

        logger.info(f"Checking: {name} (TTL: {ttl_timestamp})")

        if ttl_timestamp < now:
            logger.info(f"  EXPIRED! Processing {name}")

            # Check if this is a warm pool pod
            pod_labels = deployment.metadata.labels or {}
            is_warm_pool = pod_labels.get("pool-type") == "warm"

            if is_warm_pool:
                # Return warm pool pod to pool instead of deleting
                logger.info(f"  {name} is a warm pool pod - returning to pool")
                # Delete clone-specific resources first
                _delete_clone_resources_only(name, namespace, core_api, networking_api)
                try:
                    # Get the pod name from deployment
                    pods = core_api.list_namespaced_pod(
                        namespace=namespace, label_selector=f"app={name}"
                    )

                    if pods.items:
                        pod_name = pods.items[0].metadata.name
                        # Reset and return to pool
                        import asyncio

                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(warm_pool.return_to_pool(pod_name))
                            logger.info(f"  Returned {pod_name} to warm pool")
                            returned_count += 1
                        finally:
                            loop.close()
                    else:
                        logger.warning(f"  No pods found for deployment {name}")

                except Exception as e:
                    logger.error(f"  Failed to return {name} to pool: {e}")
                    logger.info(f"  Falling back to deletion")
                    _delete_clone(name, namespace, apps_api, core_api, networking_api)
                    deleted_count += 1
            else:
                # Regular clone - delete as before
                logger.info(f"  {name} is a regular clone - deleting")
                _delete_clone(name, namespace, apps_api, core_api, networking_api)
                deleted_count += 1
        else:
            remaining = (ttl_timestamp - now) // 60
            logger.info(f"  Valid ({remaining}min remaining)")

    # Also check for orphaned pods with ttl-expires-at label
    # (pods whose deployments were already deleted)
    logger.info("Checking for orphaned pods with ttl-expires-at label...")
    pods = core_api.list_namespaced_pod(
        namespace=namespace, label_selector="app=wordpress-clone,ttl-expires-at"
    )
    logger.info(
        f"Found {len(pods.items)} pods with app=wordpress-clone,ttl-expires-at labels"
    )

    for pod in pods.items:
        name = pod.metadata.name
        logger.info(f"  Evaluating pod: {name}")

        # Skip if this pod belongs to an existing deployment
        owner_refs = pod.metadata.owner_references or []
        if owner_refs:
            logger.info(f"    Skipping {name} - has owner references")
            continue

        # Check for ttl-expires-at label
        ttl_label = pod.metadata.labels.get("ttl-expires-at")
        if not ttl_label:
            logger.info(f"    Skipping {name} - no ttl-expires-at label")
            continue

        try:
            ttl_timestamp = int(ttl_label)
        except ValueError:
            logger.warning(f"Invalid TTL label for pod {name}: {ttl_label}")
            continue

        logger.info(f"Checking orphaned pod: {name} (TTL: {ttl_timestamp})")

        if ttl_timestamp < now:
            logger.info(f"  EXPIRED! Processing {name}")

            # Check if this is a warm pool pod
            pod_labels = pod.metadata.labels or {}
            clone_id = pod_labels.get("clone-id")
            is_warm_pool = pod_labels.get("pool-type") in ["warm", "assigned"]

            if is_warm_pool:
                logger.info(f"  {name} is a warm pool pod - returning to pool")
                # Clean up associated resources first
                if clone_id:
                    _delete_clone_resources_only(
                        clone_id, namespace, core_api, networking_api
                    )

                try:
                    import asyncio

                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(warm_pool.return_to_pool(name))
                        logger.info(f"  Returned {name} to warm pool")
                        returned_count += 1
                    finally:
                        loop.close()
                except Exception as e:
                    logger.error(f"  Failed to return {name} to pool: {e}")
                    logger.info(f"  Deleting orphaned pod {name}")
                    try:
                        core_api.delete_namespaced_pod(name, namespace)
                        # Delete pod's secret
                        try:
                            core_api.delete_namespaced_secret(
                                f"{name}-credentials", namespace
                            )
                        except:
                            pass
                        deleted_count += 1
                    except:
                        pass
            else:
                logger.info(f"  {name} is a regular clone pod - deleting")
                # Clean up associated resources
                if clone_id:
                    _delete_clone_resources_only(
                        clone_id, namespace, core_api, networking_api
                    )
                try:
                    core_api.delete_namespaced_pod(name, namespace)
                    # Delete pod's secret
                    try:
                        core_api.delete_namespaced_secret(
                            f"{name}-credentials", namespace
                        )
                    except:
                        pass
                    deleted_count += 1
                except:
                    pass

    logger.info(
        f"Cleanup complete. Deleted: {deleted_count}, Returned to pool: {returned_count}"
    )
    return {"deleted": deleted_count, "returned": returned_count}


def _delete_clone_resources_only(name: str, namespace: str, core_api, networking_api):
    """Delete clone service, ingress and secret (for warm pool returns)"""
    # Delete service
    try:
        core_api.delete_namespaced_service(
            name=name,
            namespace=namespace,
            body=client.V1DeleteOptions(grace_period_seconds=0),
        )
    except Exception:
        pass

    # Delete ingress
    try:
        networking_api.delete_namespaced_ingress(
            name=name,
            namespace=namespace,
            body=client.V1DeleteOptions(grace_period_seconds=0),
        )
    except Exception:
        pass

    # Delete credentials secret
    try:
        core_api.delete_namespaced_secret(
            name=f"{name}-credentials",
            namespace=namespace,
            body=client.V1DeleteOptions(grace_period_seconds=0),
        )
    except Exception:
        pass

    logger.info(f"  Cleaned up resources for {name}")


def _delete_clone(name: str, namespace: str, apps_api, core_api, networking_api):
    """Delete clone deployment and associated resources"""

    # Delete deployment
    apps_api.delete_namespaced_deployment(
        name=name,
        namespace=namespace,
        body=client.V1DeleteOptions(grace_period_seconds=0),
    )

    # Delete service
    try:
        core_api.delete_namespaced_service(
            name=name,
            namespace=namespace,
            body=client.V1DeleteOptions(grace_period_seconds=0),
        )
    except Exception:
        pass

    # Delete ingress
    try:
        networking_api.delete_namespaced_ingress(
            name=name,
            namespace=namespace,
            body=client.V1DeleteOptions(grace_period_seconds=0),
        )
    except Exception:
        pass

    # Delete credentials secret
    try:
        core_api.delete_namespaced_secret(
            name=f"{name}-credentials",
            namespace=namespace,
            body=client.V1DeleteOptions(grace_period_seconds=0),
        )
    except Exception:
        pass

    logger.info(f"  Deleted {name}")


if __name__ == "__main__":
    cleanup_expired_clones()
