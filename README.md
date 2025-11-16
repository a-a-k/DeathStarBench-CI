# DeathStarBench CI Demo

This repository is a demonstration fork of DeathStarBench that spotlights the **Social Network** microservice application and its resilience workflow. The entire experience is automated inside GitHub Actions so you can evaluate the service, gate a release, and publish a dashboard without provisioning local infrastructure. Treat it as an educational sandbox rather than a production deployment.

## What's in the demo

- `socialNetwork/` - the full Social Network application with all services, Docker Compose profiles, and the web frontend used in CI.
- `socialNetwork/resilience-demo/` - offline Jaeger artifacts (`deps.json`) plus replica definitions (`norepl.yaml`, `replicas.yaml`) together with `simulate.py`, `gate.py`, and `report.py`.
- `wrk2/` and `socialNetwork/wrk2/` - workload generators and Lua scripts driven by the workflow during warm-up.
- GitHub Actions workflow `.github/workflows/social-network-resilience.yml` - orchestrates the stack start-up, dependency snapshot, simulations, release gate, and GitHub Pages deployment.

## Run everything from GitHub

1. **Prepare your repository.**
   - Fork or import this project.
   - Go to *Settings ▸ Pages* and keep the default `gh-pages` branch (the workflow will create it automatically).
   - Make sure GitHub Actions are enabled under *Settings ▸ Actions*.
2. **(Optional) Set default inputs via repository variables.** Navigate to *Settings ▸ Variables* and define any of the following overrides:

   | Variable | Purpose | Default |
   | --- | --- | --- |
   | `SN_THRESHOLD` | Reliability gate cutoff applied by `gate.py`. | `0.95` |
   | `SN_PFAIL_SET` | JSON array of failure probabilities to simulate. | `[0.1, 0.3, 0.5]` |
   | `SN_ENDPOINT_FILTERS` | Comma-separated endpoint keys checked by the gate (empty = all). | *(empty)* |
   | `SN_GATE_MODE` | `any` (fail when any endpoint drops below threshold) or `mean` (use average). | `any` |

   You can still override these values per run via workflow inputs.

3. **Dispatch the workflow.**
   - Open the *Actions* tab, select **Social Network resilience demo**, and click **Run workflow**.
   - Choose the branch you want to exercise (usually `master`).
   - Fill the optional fields:

     | Input field | Maps to env var | Description |
     | --- | --- | --- |
     | `threshold` | `THRESHOLD` | Overrides the reliability gate cutoff. |
     | `pfail_set` | `PFAIL_SET` | JSON array of prior failure probabilities. |
     | `endpoint_filters` | `ENDPOINT_FILTERS` | Comma-separated endpoints (e.g. `/compose,/timeline`). Empty means evaluate all entry points. |
     | `gate_mode` | `GATE_MODE` | `any` (default) or `mean`, matching the options accepted by `gate.py`. |

   - Click **Run workflow**. GitHub queues a run exactly like the screenshot above.

4. **Watch the jobs.**
   - `collect-dependencies` boots the Social Network stack via Docker Compose on the runner, seeds the graph, drives a mixed workload with `wrk2`, captures a Jaeger dependency snapshot, and uploads `deps.json`.
   - `simulate` fans out across the requested `pfail` values, running `simulate.py` twice per value (no replicas vs replicas) and storing JSON reports.
   - `gate-and-report` evaluates the release gate with your inputs, emits a JSON summary, renders `report/index.html`, and uploads the `gh-pages` artifact.
   - `deploy` publishes the static dashboard to GitHub Pages; `enforce-gate` fails the workflow if the gate did not pass.

5. **Review the results.**
   - The run summary shows whether the gate passed along with the reason from `gate.py`.
   - Download the `social-network-resilience-*` artifacts for raw JSON outputs if you need to inspect per-endpoint reliabilities.
   - Browse to `https://<your-account>.github.io/DeathStarBench-CI/` (or the preview URL linked in the workflow logs) to see the rendered dashboard.

6. **Iterate.** Re-run the workflow with different `pfail_set`, `endpoint_filters`, or `threshold` values to explore alternative what-if scenarios. Each run produces a new GitHub Pages revision without touching your local machine.

> Want to reproduce the flow manually? The project-level guide at `socialNetwork/README.md` documents every container, load generator, and script used by the workflow so you can run them outside of GitHub Actions when needed.

## Repository layout

- `daprApps_v1/`, `hotelReservation/`, `mediaMicroservices/`, `wrk2/` - additional DeathStarBench services that ship as-is for completeness.
- `ms_collecter/` and `socialNetwork/nginx-web-server/` - helper services and configs used by the demo.
- `socialNetwork/README.md` - deep dive guide for the Social Network project and manual workflows.

## License

The project is distributed under GNU GPLv2. Source material comes from ["An Open-Source Benchmark Suite for Microservices and Their Hardware-Software Implications for Cloud and Edge Systems"](http://www.csl.cornell.edu/~delimitrou/papers/2019.asplos.microservices.pdf). Please cite the paper and the original DeathStarBench project when you publish results.
