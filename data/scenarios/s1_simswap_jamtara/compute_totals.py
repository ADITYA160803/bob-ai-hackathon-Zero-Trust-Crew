"""
compute_totals.py — computes exact totals from transactions.csv for expected.json
Run: python3 data/scenarios/s1_simswap_jamtara/compute_totals.py
"""
import csv
from collections import defaultdict

SCENARIO_DIR = "jaal/data/scenarios/s1_simswap_jamtara"

def load_csv(fname):
    with open(f"{SCENARIO_DIR}/{fname}") as f:
        return list(csv.DictReader(f))

txns = load_csv("transactions.csv")

# Filter valid (non-zero) transactions
valid = [t for t in txns if int(t["amount_inr"]) > 0]

# Victim accounts (ACC_V*)
victim_accounts = {t["from_account"] for t in valid if t["from_account"].startswith("ACC_V")}

# Total loss = sum of victim->mule transactions
victim_txns = [t for t in valid if t["from_account"].startswith("ACC_V")]
total_loss = sum(int(t["amount_inr"]) for t in victim_txns)
print(f"Victim accounts: {sorted(victim_accounts)}")
print(f"Total victim->mule transactions: {len(victim_txns)}")
print(f"Total loss INR: {total_loss}")

# Mule pass-through
mule_accounts = {t["from_account"] for t in valid if t["from_account"].startswith("ACC_M")}
print(f"\nMule accounts: {sorted(mule_accounts)}")

# Per-mule: received, sent
mule_in  = defaultdict(int)
mule_out = defaultdict(int)
for t in valid:
    if t["to_account"].startswith("ACC_M"):
        mule_in[t["to_account"]] += int(t["amount_inr"])
    if t["from_account"].startswith("ACC_M"):
        mule_out[t["from_account"]] += int(t["amount_inr"])

for m in sorted(mule_in):
    r = mule_out[m] / mule_in[m] if mule_in[m] else 0
    print(f"  {m}: in={mule_in[m]}, out={mule_out[m]}, pass-through-ratio={r:.2f}")

# Handler totals
handler_in = defaultdict(int)
handler_out = defaultdict(int)
for t in valid:
    if t["to_account"].startswith("ACC_H"):
        handler_in[t["to_account"]] += int(t["amount_inr"])
    if t["from_account"].startswith("ACC_H"):
        handler_out[t["from_account"]] += int(t["amount_inr"])

print(f"\nHandler received:")
for h in sorted(handler_in):
    print(f"  {h}: in={handler_in[h]}, out={handler_out[h]}")

# Kingpin total
king_in = sum(int(t["amount_inr"]) for t in valid if t["to_account"] == "ACC_K1")
print(f"\nKingpin ACC_K1 received: {king_in}")
print(f"Kingpin share of total loss: {king_in/total_loss*100:.1f}%")
