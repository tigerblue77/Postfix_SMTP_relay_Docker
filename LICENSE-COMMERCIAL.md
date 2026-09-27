<!--
SPDX-FileCopyrightText: 2015-2026 Mattias Wadman, Tigerblue77 and the postfix-relay contributors
SPDX-License-Identifier: AGPL-3.0-only
-->

# Commercial licence

This project is dual-licensed. It is available:

- to everyone, under the [GNU Affero General Public License version 3](./LICENSE) (`AGPL-3.0-only`), at no cost and with no formality;
- or, to those who ask for it, under a **separate commercial licence** negotiated with the copyright holder.

**The two are alternatives, and the choice is the recipient's.** Nothing here restricts the AGPL grant: taking the program under the AGPL requires no permission, no registration and no notice to anybody, and this page cannot and does not add conditions to it. If the AGPL suits you — and for the overwhelming majority of users, including businesses relaying their own mail through it in production, it does — you need nothing from this page.

## Do I need one?

Almost certainly not. Read this table before assuming otherwise.

| What you are doing | AGPL is enough | Commercial licence |
|---|:---:|:---:|
| Running the image to relay your own mail, at home | ✅ | |
| Running it for your company's or your employer's mail, in production, at any scale | ✅ | |
| Modifying it for your own use, with only your own systems sending mail through it | ✅ | |
| Publishing your modifications, under the AGPL | ✅ | |
| Redistributing the image or the scripts as-is, licence and notices intact | ✅ | |
| Offering a modified version as a relay other parties send mail through, and offering them its source as AGPL section 13 asks | ✅ | |
| Offering a modified version to other parties as a hosted or managed relay service and **declining** the section 13 source obligation | | ✅ |
| Shipping it inside a product, an appliance or a firmware, and **not** releasing your modified source under the AGPL | | ✅ |
| Bundling it into a proprietary mail or hosting suite whose source you cannot publish | | ✅ |
| Needing a warranty, an indemnity, or a support commitment — the AGPL disclaims all three (sections 15 and 16) | | ✅ |

The short version: **running** it never requires a commercial licence. Only **conveying** it, or offering a **modified** version to others over the network, while withholding the corresponding source does, and that is exactly what the AGPL asks in exchange for the grant.

Two consequences of the AGPL are worth spelling out, because they are what most commercial enquiries turn out to be about:

- **Copyleft reaches your modifications, not your infrastructure.** The applications that send mail through the relay, and the proprietary software running next to it, do not become derived works by talking SMTP to it. Mere aggregation is explicitly carved out (AGPL section 5, final paragraph).
- **Section 13 is live here, but narrow.** A relay is a network service: the containers and applications that send mail through it interact with it remotely. Section 13 asks that a *modified* version offer its source to the users interacting with it that way. Running the image as published never triggers it, and neither does a modified version that only your own systems connect to. It matters when you modify the relay and offer it to other parties.

## What the commercial licence typically covers

Terms are agreed case by case, because a licence that fits an appliance vendor does not fit a hosting provider. The usual shape is:

- a non-exclusive right to use, modify and redistribute the program in object or source form, **without** the AGPL's reciprocal source-disclosure obligations;
- the right to sublicense it as part of a larger product or service, under the licensee's own terms;
- the attribution and notice obligations reduced to what the licensee's product can practically carry;
- optionally: a warranty, an indemnity, a support or maintenance commitment, or a defined update channel — none of which the AGPL version carries.

It covers only the parts of the program whose copyright this project holds or is authorised to sublicense. It does not and cannot cover the third-party software aggregated in the published Docker image (the Debian base image, postfix, opendkim, postsrsd, rsyslog and the rest); those keep their own licences in every case. See [`NOTICE`](./NOTICE).

## How to ask

**Through GitHub — that is the channel, and there is no separate mailing address.** Open an issue on this repository describing your use case, or reach the maintainer, [@tigerblue77](https://github.com/tigerblue77), directly on GitHub. An issue is the better of the two unless what you have to say is confidential: it is seen sooner, and it leaves a record both sides can point back to.

Please include:

1. what the product or service is, and how the relay would sit inside it;
2. whether you would redistribute it, host it for others, or both;
3. the scale involved, and the obligations you specifically need lifted;
4. any warranty, indemnity or support requirement.

There is no published price list, because there is no standard case. Small-volume, hobbyist and non-profit uses that genuinely cannot fit the AGPL are usually settled for nothing at all — ask.

## Notes

- **This page is not itself a licence.** It is a description of an offer to negotiate. A commercial licence exists only once it is signed; until then, the AGPL is the only licence in force, and it applies in full.
- **Contributors:** [`CONTRIBUTING.md`](./CONTRIBUTING.md) explains why contributing to this project means granting the maintainer the right to include your contribution under both arms of the licence, and what that does and does not mean for you.
- **History:** this project was licensed under the MIT licence until the relicensing recorded in [`NOTICE`](./NOTICE). Copies obtained under those terms keep them; the relicensing withdraws nothing from anyone who already holds one.
