"""live_basket -- V0 live-basket target-state bridge (Cointegration first live
deployment, Slice 1).

The on-disk JSON bridge is the cross-process / cross-repo interface between the
Trade_Scan-side *runner* (emits desired target state) and the *shim* (reconciles
broker truth to target). The file format IS the contract (see CONTRACT.md);
`bridge` + `reconcile` are stdlib-only so the reconcile core ports to the
TS_Execution shim without taking a Trade_Scan dependency.

Slice 1 scope: prove bridge I/O + the stateless reconcile loop + restart +
incoherent-state recovery + dry end-to-end convergence, with a MOCKED broker and
a thin SCRIPTED runner. No MT5, no real basket_pipeline runner (both deferred).
"""
