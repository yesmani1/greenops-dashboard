import os
import time
import logging
from kubernetes import client, config, watch
from flask import Flask, jsonify

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

NAMESPACE = os.getenv("NAMESPACE", "boutique")
AUTO_APPLY = os.getenv("AUTO_APPLY", "false").lower() == "true"
USE_GEMINI = os.getenv("USE_GEMINI", "false").lower() == "true"

EVENTS = []
EVENTS_MAX = 500

def add_event(message):
    entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "message": message}
    EVENTS.append(entry)
    # cap event list to last EVENTS_MAX items
    if len(EVENTS) > EVENTS_MAX:
        del EVENTS[0 : len(EVENTS) - EVENTS_MAX]
    logging.info(message)

@app.route("/status")
def status():
    return jsonify(EVENTS)

def suggest_fix(pod_name, reason):
    if USE_GEMINI:
        # Placeholder for Gemini call
        return f"Gemini suggests restarting pod {pod_name} due to {reason}."
    return f"Mock fix: restart pod {pod_name} for reason {reason}."

def _safe_get_container_reason(pod):
    """Return a list of reasons observed for containers in the pod (may be empty)."""
    reasons = []
    try:
        statuses = pod.status.container_statuses or []
        for s in statuses:
            state = getattr(s, "state", None)
            if state is None:
                continue
            # waiting, terminated, running
            waiting = getattr(state, "waiting", None)
            terminated = getattr(state, "terminated", None)
            if waiting and getattr(waiting, "reason", None):
                reasons.append(getattr(waiting, "reason"))
            elif terminated and getattr(terminated, "reason", None):
                reasons.append(getattr(terminated, "reason"))
    except Exception:
        logging.exception("Error while parsing container statuses")
    return reasons


def watch_pods():
    # Try in-cluster config, fallback to kubeconfig for local dev
    try:
        config.load_incluster_config()
        logging.info("Loaded in-cluster kube config")
    except Exception:
        try:
            config.load_kube_config()
            logging.info("Loaded local kube config")
        except Exception as e:
            add_event(f"Failed to load any kube config: {e}")
            # can't proceed without kube config
            return

    v1 = client.CoreV1Api()
    w = watch.Watch()
    add_event("Starting pod watcher...")
    backoff_seconds = 1
    while True:
        try:
            for event in w.stream(v1.list_namespaced_pod, namespace=NAMESPACE, timeout_seconds=60):
                pod = event.get('object')
                if not pod:
                    continue
                reasons = _safe_get_container_reason(pod)
                for reason in reasons:
                    if reason in ["CrashLoopBackOff", "OOMKilled"]:
                        pod_name = getattr(pod.metadata, "name", "unknown")
                        fix = suggest_fix(pod_name, reason)
                        add_event(f"Detected crash: {pod_name}, reason: {reason}, suggestion: {fix}")
                        if AUTO_APPLY:
                            try:
                                v1.delete_namespaced_pod(name=pod_name, namespace=NAMESPACE)
                                add_event(f"Applied fix: deleted pod {pod_name}")
                            except Exception as e:
                                add_event(f"Error applying fix: {e}")
            # if the stream exits normally, reset backoff
            backoff_seconds = 1
        except Exception as e:
            logging.exception("Watch stream error, will retry")
            add_event(f"Watch stream error: {e}")
            time.sleep(backoff_seconds)
            backoff_seconds = min(backoff_seconds * 2, 60)

if __name__ == "__main__":
    import threading
    t = threading.Thread(target=watch_pods, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=int(os.getenv("STATUS_PORT", 8081)))
