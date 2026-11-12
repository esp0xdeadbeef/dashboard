# BUG: no port-mapping service state is materialized in any renderer

**Severity:** HIGH
**Spec:** `GAMP/SMS/FS-625-HDS-010-SDS-010-SMS-010.md` (Port-Mapping Service-State)
**Owner:** supplier renderers (`network-renderer-nixos`, and peers)
**Status:** OPEN — five focused cases fail closed and must not be weakened

## Symptom

`tests/FS-625-HDS-010-SDS-010-SMS-010.sh` .. `-SMS-050.sh` all fail with:

```
FAIL port-mapping-service-state: P1 no port-mapping service state is emitted
anywhere in the renderer; UPnP IGD, NAT-PMP and PCP are unmodelled rather than
explicitly disabled
```

## Why it is a defect, not a stale test

The SMS requires that each target carry an **explicit** port-mapping service
state, because an implicit "no service configured" is indistinguishable from
"the platform default silently enabled one":

- Render port-mapping services (UPnP IGD, NAT-PMP, PCP) disabled when the
  canonical bundle carries no modeled mapping relationship.
- Override any package or upstream default that would enable such a service.
- Fail closed when the service state cannot be determined explicitly.
- Expose the emitted service state per target so it is inspectable in the
  artifact.

No implementation repository emits any of this. A grep across all
`network-*` repositories for `upnp|natpmp|nat-pmp|portMapping|port-mapping`
finds nothing.

## Required work

1. Add a port-mapping service-state record to the rendered artifact, gated on a
   modeled mapping relationship.
2. Model the relationship fields the SMS requires before it can be accepted:
   `requesterScope`, `mappingRange`, `lifetime`, `auditBehavior`,
   `conflictHandling`, `publicExposureLimits`.
3. Emit an explicit disabled state when no relationship is modeled, and override
   any package default that would enable a service.
4. Re-run the five cases; they are written to pass unchanged.

## Do not

Do not delete, skip, or relax these cases. They encode the contract and are
marked in-file as expected to fail until the module exists.
