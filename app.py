from flask import Flask, render_template, jsonify, request
import threading
import time

app = Flask(__name__)

# État global du réseau de Petri (thread-safe)
state_lock = threading.Lock()
rdp_state = {
    "places": {"P1": 1, "P2": 0, "P3": 0, "P4": 0, "P5": 1, "P6": 0, "P7": 0},
    "history": [],
    "auto_running": False,
}

TRANSITIONS = {
    "T1": {"in": {"P1": 1, "P5": 1}, "out": {"P3": 1}, "name": "Rouge → Vert"},
    "T2": {"in": {"P3": 1}, "out": {"P2": 1}, "name": "Vert → Orange"},
    "T3": {"in": {"P2": 1}, "out": {"P4": 1}, "name": "Orange → Attente"},
    "T4": {"in": {"P4": 1}, "out": {"P1": 1, "P5": 1}, "name": "Attente → Rouge"},
    "T5": {"in": {"P5": 1}, "out": {"P6": 1}, "name": "Demande piéton"},
    "T6": {"in": {"P6": 1, "P1": 1}, "out": {"P7": 1}, "name": "Piéton traverse"},
    "T7": {"in": {"P7": 1}, "out": {"P5": 1}, "name": "Fin traversée"},
}

PLACE_META = {
    "P1": {"label": "P₁", "desc": "Rouge", "x": 150, "y": 60},
    "P2": {"label": "P₂", "desc": "Orange", "x": 390, "y": 60},
    "P3": {"label": "P₃", "desc": "Vert", "x": 150, "y": 180},
    "P4": {"label": "P₄", "desc": "Attente", "x": 390, "y": 180},
    "P5": {"label": "P₅", "desc": "Séquenceur", "x": 270, "y": 280},
    "P6": {"label": "P₆", "desc": "Piéton attente", "x": 150, "y": 360},
    "P7": {"label": "P₇", "desc": "Piéton OK", "x": 390, "y": 360},
}

TRANS_META = {
    "T1": {"x": 130, "y": 120, "w": 40, "h": 14},
    "T2": {"x": 250, "y": 120, "w": 40, "h": 14},
    "T3": {"x": 370, "y": 120, "w": 40, "h": 14},
    "T4": {"x": 250, "y": 230, "w": 40, "h": 14},
    "T5": {"x": 190, "y": 320, "w": 40, "h": 14},
    "T6": {"x": 250, "y": 360, "w": 40, "h": 14},
    "T7": {"x": 330, "y": 320, "w": 40, "h": 14},
}


def is_enabled(tid, places):
    t = TRANSITIONS[tid]
    for p, w in t["in"].items():
        if places.get(p, 0) < w:
            return False
    return True


def fire_transition(tid):
    global rdp_state
    with state_lock:
        places = rdp_state["places"]
        if not is_enabled(tid, places):
            return False
        t = TRANSITIONS[tid]
        for p, w in t["in"].items():
            places[p] -= w
        for p, w in t["out"].items():
            places[p] += w
        rdp_state["history"].append({
            "transition": tid,
            "name": t["name"],
            "time": time.strftime("%H:%M:%S"),
            "marking": dict(places),
        })
        # Keep last 50
        rdp_state["history"] = rdp_state["history"][-50:]
        return True


def get_enabled():
    return [tid for tid in TRANSITIONS if is_enabled(tid, rdp_state["places"])]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    with state_lock:
        return jsonify({
            "places": dict(rdp_state["places"]),
            "enabled": get_enabled(),
            "history": rdp_state["history"],
            "auto": rdp_state["auto_running"],
        })


@app.route("/api/fire", methods=["POST"])
def api_fire():
    tid = request.json.get("transition")
    if tid not in TRANSITIONS:
        return jsonify({"error": "Transition inconnue"}), 400
    ok = fire_transition(tid)
    with state_lock:
        return jsonify({
            "success": ok,
            "places": dict(rdp_state["places"]),
            "enabled": get_enabled(),
            "history": rdp_state["history"],
        })


@app.route("/api/reset", methods=["POST"])
def api_reset():
    global rdp_state
    with state_lock:
        rdp_state["places"] = {"P1": 1, "P2": 0, "P3": 0, "P4": 0, "P5": 1, "P6": 0, "P7": 0}
        rdp_state["history"] = []
        rdp_state["auto_running"] = False
    return jsonify({
        "places": rdp_state["places"],
        "enabled": get_enabled(),
        "history": [],
    })


@app.route("/api/export")
def api_export():
    with state_lock:
        data = {
            "type": "ReseauDePetri_FeuTricolore",
            "places": {k: {"description": v["desc"]} for k, v in PLACE_META.items()},
            "transitions": {
                k: {"name": v["name"], "pre": v["in"], "post": v["out"]}
                for k, v in TRANSITIONS.items()
            },
            "marking_initial": {"P1": 1, "P2": 0, "P3": 0, "P4": 0, "P5": 1, "P6": 0, "P7": 0},
            "marking_courant": dict(rdp_state["places"]),
            "historique": rdp_state["history"],
        }
        return jsonify(data)


def auto_loop():
    order = ["T1", "T2", "T3", "T4", "T5", "T6", "T7"]
    while True:
        with state_lock:
            if not rdp_state["auto_running"]:
                break
        fired = False
        for tid in order:
            with state_lock:
                if not rdp_state["auto_running"]:
                    break
            if is_enabled(tid, rdp_state["places"]):
                fire_transition(tid)
                fired = True
                break
        if not fired:
            time.sleep(0.3)
        else:
            time.sleep(1.0)


@app.route("/api/auto", methods=["POST"])
def api_auto():
    action = request.json.get("action")
    with state_lock:
        if action == "start":
            if not rdp_state["auto_running"]:
                rdp_state["auto_running"] = True
                threading.Thread(target=auto_loop, daemon=True).start()
        elif action == "stop":
            rdp_state["auto_running"] = False
        return jsonify({"auto": rdp_state["auto_running"]})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
