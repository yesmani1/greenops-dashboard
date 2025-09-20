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

def add_event(message):
    EVENTS.append({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "message": message})
    logging.info(message)

@app.route("/status")
def status():
    return jsonify(EVENTS)

def suggest_fix(pod_name, reason):
    if USE_GEMINI:
        # Placeholder for Gemini call
        return f"Gemini suggests restarting pod {pod_name} due to {reason}."
    return f"Mock fix: restart pod {pod_name} for reason {reason}."

def watch_pods():
    config.load_incluster_config()
    v1 = client.CoreV1Api()
    w = watch.Watch()
    add_event("Starting pod watcher...")
    for event in w.stream(v1.list_namespaced_pod, namespace=NAMESPACE, timeout_seconds=0):
        pod = event['object']
        reason = pod.status.container_statuses[0].state.waiting.reason if pod.status.container_statuses and pod.status.container_statuses[0].state.waiting else None
        if reason in ["CrashLoopBackOff", "OOMKilled"]:
            pod_name = pod.metadata.name
            fix = suggest_fix(pod_name, reason)
            add_event(f"Detected crash: {pod_name}, reason: {reason}, suggestion: {fix}")
            if AUTO_APPLY:
                try:
                    v1.delete_namespaced_pod(name=pod_name, namespace=NAMESPACE)
                    add_event(f"Applied fix: deleted pod {pod_name}")
                except Exception as e:
                    add_event(f"Error applying fix: {e}")

if __name__ == "__main__":
    import threading
    t = threading.Thread(target=watch_pods, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=int(os.getenv("STATUS_PORT", 8081)))
