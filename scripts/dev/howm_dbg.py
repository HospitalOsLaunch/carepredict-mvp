from hospitalos.howm.generator import establishment, generate
ep = generate(establishment("TRAIN", 0))
offs = [(t, k, s, v) for t, k, s, v in ep.truth_log if k.startswith("offer")]
for o in offs: print(o)
for h in (83, 84, 85):
    print(h, {k: v for k, v in ep.capacity.items() if k[2] == h}, ep.static["units"]["B"]["roster"]["IDE"][h])
