# Social Network Demo

This directory contains the demonstration build of the DeathStarBench **Social Network** application. The branch is tuned for labs and workshops: stand up every microservice quickly, seed test users, drive synthetic load, and produce the offline resilience report. It is not a production deployment; it is a guided sandbox.

![Social Network Architecture](figures/socialNet_arch.png)

## Demo capabilities

- Compose text posts with optional media (images, video, shortened URLs, user tags).
- Read home and user timelines, search posts and users, and receive follow recommendations.
- Follow or unfollow people, register, and sign in through the UI.
- Inspect distributed traces in Jaeger and compare topologies with different replica counts.

## How the GitHub workflow uses this project

The Actions workflow `social-network-resilience.yml` spins these services up on GitHub-hosted runners and automates the entire resilience demo:

1. `collect-dependencies` checks out this directory with submodules, builds `wrk2`, launches the Docker Compose stack defined in `socialNetwork/docker-compose.yml`, seeds users with `scripts/init_social_graph.py`, executes `wrk2/scripts/social-network/mixed-workload.lua`, and captures Jaeger dependencies into `resilience-demo/artifacts/deps.json`.
2. `simulate` invokes `resilience-demo/simulate.py` twice per `pfail` value (no replicas vs replicas) to produce JSON snapshots under `resilience-demo/out/`.
3. `gate-and-report` runs `gate.py` with the workflow inputs (`threshold`, `endpoint_filters`, `gate_mode`) and renders the static dashboard through `report.py`.

Tune the workflow either by filling the dispatch form (threshold, JSON array of failure priors, endpoint filters, gate mode) or by defining repository variables (`SN_THRESHOLD`, `SN_PFAIL_SET`, `SN_ENDPOINT_FILTERS`, `SN_GATE_MODE`). Use the instructions and screenshot in the root `README.md` for a GitHub-only walkthrough. The manual directions below mirror what the workflow performs on runners.

## Requirements

- Docker plus Docker Compose or Docker Swarm.
- Python 3.8+ with `asyncio`, `aiohttp`, and `pip`.
- `libssl-dev`, `libz-dev`, `luajit`, `luarocks`, `luasocket`, `make` for `wrk2`.
- A browser for the frontend and generated HTML reports.

## Quick start

1. **Clone the repository.**
   ```bash
   git clone --recurse-submodules https://github.com/<your-account>/DeathStarBench-CI.git
   cd DeathStarBench-CI/socialNetwork
   ```
2. **Launch the services.**
   ```bash
   docker compose up -d
   # Jaeger UI: http://localhost:16686, frontend: http://localhost:8080
   ```
3. **Initialize the dataset.**
   ```bash
   python3 scripts/init_social_graph.py --graph socfb-Reed98 --ip localhost --port 8080
   ```
4. **Use the browser.** Go to `http://localhost:8080`, sign up, author a couple of posts, and follow the default recommendations.
5. **Generate load with wrk2.**
   ```bash
   cd ../wrk2 && make
   cd ../socialNetwork
   ../wrk2/wrk -D exp -t 8 -c 128 -d 120 -L \
     -s ./wrk2/scripts/social-network/compose-post.lua http://localhost:8080/wrk2-api/post/compose -R 200
   ```
6. **Inspect traces.** Jaeger populates automatically. Look under `compose-post-service` to verify spans from the workload.
7. **Shut everything down.** Run `docker compose down` (add `-v` to drop volumes) when you finish.

## Workload scripts

- `compose-post.lua`, `read-home-timeline.lua`, and `read-user-timeline.lua` live in `wrk2/scripts/social-network/`.
- The commands above are templates; adjust `-t`, `-c`, and `-R` to match your test plan.
- When cloning on ARM hardware, rely on the published Docker images. Build `wrk2` on x86_64 for best compatibility.

## Frontend tour

Once `docker compose up -d` completes, the following routes are available:
- `http://localhost:8080` - login and registration.
- `http://localhost:8080/main.html` - preloads default users into the database.
- `http://localhost:8080/user-timeline.html` and `/home-timeline.html` - individual vs aggregated feeds.
- `http://localhost:8080/contact.html` - manage follow relationships.

## Advanced modes

- **Docker Swarm:**
  ```bash
  docker stack deploy --compose-file docker-compose-swarm.yml social-network
  ```
  Ensure the repository lives under the same path on every node.
- **TLS:**
  ```bash
  docker compose -f docker-compose-tls.yml up -d
  ```
  For Swarm you must also enable TLS manually inside `config/*.conf` and `nginx-web-server/conf/nginx.conf`.
- **Redis sharding:**
  ```bash
  docker compose -f docker-compose-sharding.yml up -d
  ```

## Resilience demo

The `resilience-demo/` directory replays the resilience scenario without reaching a live Jaeger instance.

```bash
cd resilience-demo
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 simulate.py --graph artifacts/deps.json --replicas artifacts/norepl.yaml --pfail 0.1 --out results/norepl-0.1.json
python3 simulate.py --graph artifacts/deps.json --replicas artifacts/replicas.yaml --pfail 0.1 --out results/repl-0.1.json
python3 gate.py --results results --threshold 0.95 --summary results/gate-summary.json
python3 report.py --results results --summary results/gate-summary.json --html results/index.html
```

- Set the `JAEGER_URL` environment variable to refresh `deps.json` automatically before running the simulator.
- Pass `--filters=/compose,/timeline` to focus the gate on specific HTTP endpoints.
- `results/index.html` matches the static dashboard that GitHub Actions publishes to `gh-pages`.

## Questions

File an issue or open a pull request if you improve the demo, or contact microservices-bench-L@list.cornell.edu for general questions.
