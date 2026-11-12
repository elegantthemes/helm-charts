# DeepHive

## Codex read-only sandbox on the shared worker

`CODEX_SANDBOX_APPARMOR_PROFILE` is the host-installed AppArmor profile name.
An empty value preserves existing rendering. When configured, the chart attaches
it as `securityContext.appArmorProfile.type: Localhost` only on the shared
`deephive` coding container, explicitly dropping SYS_ADMIN. Intake, sidecars,
runner/controller and task sessions are unchanged. No privilege, host mount, or
runtime environment variable is added. Kubelet refuses startup if the named
profile is missing; do not switch to Unconfined to work around that failure.

Prepare the selected node through the cluster companion before activating the
profile. The node must permit unprivileged user namespaces and have the named
profile loaded while retaining Ubuntu's global AppArmor userns restriction.
Use the Terraform app companion to pin the worker to that prepared node and
select this chart version. Installation does not itself prove real job health.

Validation: `python3 tests/deephive-codex-sandbox.py` (PyYAML), plus the existing
`tests/deephive-admission/render.py` suite. The controlled live canary established
successful reads and rejected overwrite/create/delete using the proposed host
profile; all temporary node/profile changes were restored afterward.
