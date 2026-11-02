# Electronic Component Inventory Naming Convention

**Status:** Approved | **Scope:** Electronics and electrical components only | **Version:** 1.0

## Purpose

Names should tell a person *what the part is* and its most useful specifications before showing supplier identifiers. They must work in Homebox search results, compact list views, and AI-assisted item creation. This document does not establish a naming standard for non-electronic possessions.

## Naming rule

`Component type + primary value / dimensions + defining properties + optional useful manufacturer / family`

- **Always begin with the component type**, e.g. `Resistor`, `Capacitor`, `Connector Housing`, `Crimp Contact`, `PCB Header`, `Wire`, `Diode`, `IC`, `Fuse`.
- Follow with distinguishing technical attributes in a consistent category-specific order. Use compact unit notation such as `6.8Ω`, `5W`, `2.54mm`, `22AWG`, `100µF`, `25V`, and `±5%`.
- Include **manufacturer selectively** when it materially aids selection, compatibility, reliability, or differentiation: Molex connectors, Panasonic capacitors, Alpha Wire products, and specialised semiconductors are typical examples. Do **not** routinely include the resistor manufacturer. The manufacturer must also be saved in the dedicated manufacturer field when known.
- Store manufacturer part numbers in the Homebox **model number** field, and supplier references (RS, Farnell, Mouser, etc.) in notes or appropriate searchable custom fields; **never prefix the item name with an RS stock number**. Include a manufacturer part number in a title when it is the essential identifying attribute, notably ICs and transistors.
- Preserve exact product family and polarisation/locking terminology when technically significant; do not call a metal contact a housing or a female socket a male pin.
- Never invent technical specifications. Omit unverified properties or mark uncertainties in description/notes; verify from packaging, datasheets, and delivery documents where possible.
- Keep **quantity and location out of the title**. Use the quantity field and physical location hierarchy (e.g. `Attic → FM2 → 1.4`). Record original pack quantity separately from current confirmed stock when they differ or the latter is unknown.
- Group multiple photos (packaging front/back, contents, reel labels) into **one item** per distinct SKU. Attach photos to that item, not separate duplicate records.
- Record sourced purchase/dispatch dates accurately, distinguish them, and never infer missing order numbers.

## Category-specific patterns

| Category | Recommended order | Example |
| --- | --- | --- |
| Resistor | Type, resistance, power, tolerance if known, construction / package | `Resistor 6.8Ω 5W ±5% Ceramic Wirewound` |
| Capacitor | Type, capacitance, voltage, dielectric / construction, manufacturer if useful, package | `Capacitor 100µF 25V Panasonic Electrolytic Radial` |
| Connector housing | Type, number of positions, gender, pitch, manufacturer / family, retention | `Connector Housing 3-Pin Female 2.54mm Molex Friction Lock` |
| PCB header | Type, number of positions, gender, pitch, manufacturer, orientation / retention | `PCB Header 3-Pin Male 2.54mm Molex Vertical Friction Lock` |
| Crimp contact | Type, gender, wire gauge, manufacturer, plating and contact family | `Crimp Contact Female 22–24AWG Molex Gold-Plated KK 254` |
| Hook-up wire | Type, gauge, colour, conductor, manufacturer if useful, insulation / rating | `Wire 22AWG Red Stranded Alpha Wire SR-PVC 300V` |
| Diode | Type, manufacturer part number, voltage / current, package | `Diode 1N4007 1000V 1A DO-41` |
| Transistor | Type, manufacturer part number, polarity / technology, package | `Transistor 2N3904 NPN TO-92` |
| IC | Type, full manufacturer part number, function, package | `IC NE555 Timer DIP-8` |
| Fuse | Type, current, voltage, blow speed, physical size | `Fuse 2A 250V Slow-Blow 5×20mm` |

Examples illustrate formatting, not verified specifications for new inventory items.

## FM2 migration — 2026-11-02

Existing RS references were retained in metadata; the nine names were changed to:

| RS stock | Item title |
| --- | --- |
| 670-3932 | Connector Housing 3-Pin Female 2.54mm Molex Friction Lock |
| 670-6293 | Crimp Contact Female 22–24AWG Molex Gold-Plated KK 254 |
| 679-5583 | PCB Header 2-Pin Male 2.54mm Molex Vertical Friction Lock |
| 679-5587 | PCB Header 3-Pin Male 2.54mm Molex Vertical Friction Lock |
| 683-5543 | Resistor 5.6Ω 1W ±5% Axial |
| 199-7696 | Resistor 6.8Ω 5W ±5% Ceramic Wirewound |
| 148-281 | Resistor 120Ω 0.6W Metal Film Axial |
| 168-0764 | Wire 22AWG Red Stranded Alpha Wire SR-PVC 300V |
| 168-0657 | Wire 24AWG Black Stranded Alpha Wire SR-PVC 300V |

This guidance is a documented convention, **not an enforced validator**. Future AI item creation should propose names using this rule and ask for approval of uncertain identification before writing records. A wider naming standard for all household and mechanical inventory will be defined separately.
