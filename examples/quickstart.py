"""
Engram — quickstart example
Run: python examples/quickstart.py
Requires: OPENAI_API_KEY and ANTHROPIC_API_KEY env vars, Postgres running (see docker-compose.yml)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from path_memory import Memory, recall, run_decay

# 1. Save some memories (auto-embeds, classifies, and generates fan-out lenses)
print("Saving memories...")
Memory.save("Auth decision", "We use short-lived JWTs; refresh tokens live in an httpOnly cookie.",
            person="my-project", project="backend")
Memory.save("Caching gotcha", "The cache silently drops values over 1MB — chunk big payloads.",
            person="my-project", project="backend")
Memory.save("Why Postgres", "Chose Postgres over Mongo for transactional integrity on the orders table.",
            person="my-project", project="backend")

# 2. Recall by meaning — and by the *questions a memory answers*, not just keywords.
#    "how do we keep users logged in" never appears in the text, but the JWT
#    memory's 'questions' lens makes it findable anyway.
print("\nRecalling: 'how do we keep users logged in'")
for r in recall("how do we keep users logged in", person="my-project", project="backend"):
    print(f"  [{r['id']}] {r['subject']} (score={r['score']:.3f}, weight={r['weight']:.3f})")

# 3. Each recall increments weight — importance emerges from use, not assignment.
print("\nStrongest memories for my-project:")
for m in Memory.list_by_entity("my-project"):
    print(f"  w={m['weight']:.3f} ({m['access_count']}x) — {m['subject']}")

# 4. Decay unused memories.
print("\nRunning decay...")
decayed, archived = run_decay(days_inactive=1)
print(f"  Decayed: {decayed}, Archived: {archived}")
