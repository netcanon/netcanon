# Banner + CLI-only directives — NETCONF -> CLI direction

For the full enumeration of CLI-rich-but-OpenConfig-empty fields
(banner motd, service timestamps, ACLs, route-maps, EXEC commands)
see the sibling file
`../cisco_iosxe_cli_to_cisco_iosxe/banner-and-cli-only.md`.

## Direction-specific disposition

In the **NETCONF -> CLI** direction these fields are uniformly
`not_applicable`:

* The OpenConfig source never carries banner motd, EXEC banners, or
  `service timestamps` directives — the OpenConfig schema has no
  slot for them.
* `!` separator lines, blank lines, and operator comment lines are
  artefacts of the CLI text format; they don't exist in any YANG
  model and therefore can't be in the NETCONF source.
* ACLs, route-maps, crypto, QoS, AAA policy — out of canonical
  scope on both codecs (and on the canonical model itself).

The CLI render emits a clean `running-config` text without these
features.  An operator who feeds that render back into a real
IOS-XE device will get a working configuration that lacks the
banner / timestamp / ACL stanzas the original device had — but
that's because **the NETCONF source already lacked them**.  The
codec pair is faithful to its input; the upstream `<get-config>`
boundary is where the lossy projection happened.

This is an important framing for operators: NETCONF is not a
faithful representation of CLI.  It is a **lossy projection** of
the device's running-config through the YANG model layer.  Going
NETCONF -> CLI gives you back a faithful rendering of the
projection, not a recovery of the original CLI.

For operators who need full CLI fidelity, the right capture
mechanism is the CLI source codec consuming `show running-config`
output directly — which is precisely the bidirectional `cisco_iosxe_cli`
codec's role.
