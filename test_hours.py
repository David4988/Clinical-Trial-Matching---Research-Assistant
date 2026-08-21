steps = int((16.0 * 60) // 15)
stamps = list(range(steps + 1))
size = max(len(stamps) // 5, 1)
print(f"Steps: {steps}, Total stamps: {len(stamps)}, Size per window: {size}")
for w in range(5):
    idx = w * size
    batch = stamps[idx:idx+size]
    if w == 4:
        batch.extend(stamps[idx+size:]) # Fold remainder
    history = batch[-1] * 15
    print(f"Window {w}: stamps {len(batch)}, max history: {history} mins")
