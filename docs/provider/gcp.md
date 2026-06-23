# Google Cloud Runtime Notes

For ATSuite, Google Cloud support is centered on containerized deployment to Cloud Run, with related services such as Artifact Registry, Cloud Storage, Cloud Logging, and Cloud Monitoring.

## Compute

Cloud Run is the primary target for both function-style tools and MCP services. ATSuite builds a container image, pushes it to the configured registry, deploys it with `gcloud run deploy`, and records the service URL.

## Storage and Logs

- Cloud Storage can be used for stateful artifacts and benchmark data.
- Cloud Logging and Cloud Monitoring provide provider-side evidence for latency, execution, and resource metrics.

## Typical Services

- Artifact Registry or GCR for container images.
- Cloud Run for deployed services.
- Cloud Storage for object storage.
- Cloud Logging for provider logs.
