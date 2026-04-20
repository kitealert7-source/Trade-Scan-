import yaml
import random
import itertools
import copy
from pathlib import Path

# ----------------------------
# utilities
# ----------------------------

def load_yaml(p):
    with open(p) as f:
        return yaml.safe_load(f)

def save_yaml(data, p):
    with open(p, "w") as f:
        yaml.dump(data, f, sort_keys=False)

def set_nested(d, key, value):
    keys = key.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


# ----------------------------
# sweep methods
# ----------------------------

def grid_sweep(params):
    keys = list(params.keys())
    values = [params[k]["values"] for k in keys]

    combos = []
    for combo in itertools.product(*values):
        d = dict(zip(keys, combo))
        combos.append(d)

    return combos


def grouped_sweep(params):

    combos = []

    for k, cfg in params.items():
        for v in cfg["values"]:
            combos.append({k: v})

    return combos


def random_sweep(params, n):

    combos = []

    keys = list(params.keys())

    for _ in range(n):
        d = {}
        for k in keys:
            d[k] = random.choice(params[k]["values"])
        combos.append(d)

    return combos


def latin_hypercube(params, n):

    keys = list(params.keys())
    combos = []

    for i in range(n):

        d = {}

        for k in keys:

            values = params[k]["values"]

            step = len(values) / n
            idx = int((i + random.random()) * step)

            idx = min(idx, len(values)-1)

            d[k] = values[idx]

        combos.append(d)

    return combos


# ----------------------------
# main generator
# ----------------------------

def generate(spec_file):

    spec = load_yaml(spec_file)

    template = load_yaml(spec["template"])
    outdir = Path(spec["output_dir"])
    outdir.mkdir(parents=True, exist_ok=True)

    base_name = spec["id"]
    params = spec["parameters"]
    mode = spec.get("mode", "grouped")

    if mode == "grid":
        combos = grid_sweep(params)

    elif mode == "grouped":
        combos = grouped_sweep(params)

    elif mode == "random":
        combos = random_sweep(params, spec["samples"])

    elif mode == "lhs":
        combos = latin_hypercube(params, spec["samples"])

    else:
        raise ValueError("Unknown sweep mode")

    p = 1

    for combo in combos:

        d = copy.deepcopy(template)

        for k, v in combo.items():
            set_nested(d, k, v)

        pslot = f"P{p:02}"
        name = f"{base_name}_{pslot}"

        d["test"]["name"] = name
        d["test"]["strategy"] = name

        outfile = outdir / f"{name}.txt"
        save_yaml(d, outfile)

        print(f"[CREATED] {outfile.name}")

        p += 1

    print(f"\nGenerated {len(combos)} directives.")


if __name__ == "__main__":

    import sys
    generate(sys.argv[1])