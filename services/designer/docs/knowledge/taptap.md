# TapTap component knowledge

## Source and scope

- Source: `TapTap Design System丨Developers (Community)` (`tab-2` at snapshot time).
- Snapshot: 3,125 entries across 36 pages: 251 component sets and 2,874 components.
- Full evidence: [taptap-components.catalog.json](taptap-components.catalog.json).
- No design variables were exposed by OpenPencil. Use the real component visuals;
  do not reconstruct them from guessed tokens.

`document_id` and node IDs identify this live snapshot only. Resolve by page,
family and variant properties before falling back to an ID.

## Selection algorithm

1. Map the UI requirement to a public page below.
2. Select the semantic family: for example `Button/Primary`, `Input/Basic`, or
   `Alert/Help text`.
3. Choose the normal resting variant first: `State=Default`, no optional icon,
   and the size appropriate to the layout.
4. Add only variants required by the specification: destructive, disabled,
   selected, error, loading, upload progress, and so on.
5. Bind text and replace slots using the catalog's `detail.propCandidates`.
6. Compose instances in the output document. Never lay out the source library page.

Default sizing guidance:

- `Large`: primary CTA, spacious forms, mobile touch targets.
- `Medium`: normal desktop forms, toolbars and tables.
- `Small`: dense secondary controls only.
- Use icon-only controls only when the icon is unambiguous and an accessible label
  exists in the UI specification.

## Inventory and routing

| Need | Page | Main families or axes |
| --- | --- | --- |
| Primary and secondary actions | `Button` | Primary, Outline, Ghost, Link; Size, State, Left/Right Icon |
| Segmented actions | `ButtonGroup` | Basic or Icon only; Position, Size, State |
| Navigation path | `Anchor`, `Breadcrumb` | Anchor; Breadcrumb Truncated |
| Page navigation | `Pagination` | Item Status; Pagination Basic/Advanced/Simple |
| Content switching | `Tabs` | Item, Item-Container, Basic, Container |
| Progress through a flow | `Steps` | Current/Error/Finished/Wait; Base/Vertical |
| Text and numeric entry | `Input` | Basic, Left icon, Right icon, Number, Prefix/Suffix |
| Long text | `Textarea` | State, Text Entered |
| Single or multiple choice | `Select`, `Dropdown`, `Cascader` | Basic, Multiple, With Search, grouped Item, Level |
| Boolean choice | `Checkbox`, `Radio`, `Toggle`, `Slider` | Checked/State/Disable/Marks/Tooltips |
| Date and time | `Date & Time Picker` | Date, Time, Range, Comparison, Advanced |
| File and image input | `Upload` | Picture, File, Avatar, file icons |
| Form composition | `Form` | Label placement |
| Move items between lists | `Transfer` | Small/Medium, Proportion, State |
| Dense records | `Table` | Title; single/multi-line cells; picture and action cells |
| Data visualization | `Chart` | Line, Column, Area, Donut/Pie, Stacked bar, tooltips |
| Metadata | `Badge`, `Tag`, `Audit Status`, `Filter item` | count, checkable, review and approval states |
| Inline guidance | `Tooltips`, `Popover` | placement variants |
| Status and validation | `Alert`, `Message`, `Result` | Info/Success/Warning/Error |
| Confirmation | `Popconfirm` | Basic or With Input; placement |
| Blocking task | `Dialog` | Basic, Warning, Scrollable, With divider; size |
| Side task | `Drawer` | Basic or With Cards; placement and size |
| Visual symbol | `Icon` | semantic name and Fill/Line theme |

`Internal Only Canvas` contains 1,581 support and duplicate entries. It is a
fallback source, not the normal discovery page. Prefer a public page with the same
family.

## Important family rules

### Buttons

The `Button` page contains duplicate family names for normal and destructive
examples. Use the snapshot set IDs to disambiguate, then still verify the variant
name:

| Intent | Primary | Outline | Ghost | Link |
| --- | --- | --- | --- | --- |
| Normal | `0:13924` | `0:15136` | `0:16348` | `0:17566` |
| Destructive | `0:14530` | `0:15742` | `0:16957` | `0:18048` |

Text buttons have 36 variants: `Size × State × Left Icon × Right Icon`. The normal
large primary default without icons is `0:14042`. Icon-button families are
`0:18416`, `0:18643`, and `0:18890`.

### Inputs and selection

- Basic input set: `0:29666`. Use `Text Entered=False` for placeholders and `True`
  for values. `Pressed & Focus` represents focus. `State 2` is only relevant to a
  clear affordance.
- Left/right icon variants are separate families, not a boolean option on Basic.
- Number and prefix/suffix are specialized families; do not imitate them with loose
  text beside a Basic input.
- Basic select set: `0:33984`; multiple select: `0:34489`; borderless select:
  `0:35542`.
- Some source slot names contain the typo `fleld`. Treat catalog names as opaque
  identifiers and do not silently correct them during binding.

### Feedback and overlays

- `Alert/Basic` supports action, layout, size, and status. `Help text` is for local
  validation or field-level guidance.
- `Message` is transient feedback; `Result` is a full outcome state.
- `Popover` explains or exposes non-blocking content. `Popconfirm` asks for a small
  confirmation. `Dialog` handles a focused task; `Drawer` preserves page context.

### Data display

- Build tables from header/cell/action families. Do not stretch a single cell
  component into an entire table.
- Pick chart family from data semantics, not aesthetics: line/area for change,
  column/bar for comparison, donut/pie only for a small part-to-whole set.
- `Tag-Review` and `Approval Status` include source spellings such as `Cancle`.
  Match the exact variant value in the catalog.

## Content binding

The catalog records candidates discovered from real instances:

- `text:<node name>` means editable visible copy.
- `slot:<node name>` means replaceable nested content such as an icon, prefix,
  picture, action, or menu body.

Binding order:

1. Resolve the exact variant.
2. Create or import a local component definition into the output document.
3. Create the instance.
4. Bind text, then icons/media, then layout the instance.
5. Validate the rendered output, not only the node tree.

Keep labels short enough for the selected size. Never change internal colors,
radius, or typography to compensate for a wrong semantic family.

## OpenPencil workflow and known limitations

Cross-document `create_instance` does not resolve a source component ID directly.
Use this reliable flow:

1. Read the source component with `get_jsx`.
2. Render it into a hidden/local `Components` page in the new output document.
3. Create instances from that local component definition.
4. Save the output as a separate `.fig` file.

After `reparent_node` into a non-auto-layout slot, explicitly set the child's local
`x=0, y=0`; reparenting can preserve its old absolute position.

Some OpenPencil exports do not rasterize text overrides inside an instance. If the
node tree is correct but exported text is stale, add a visible text overlay inside
the intended slot, mark it `ABSOLUTE`, and position it after the instance is sized.
Use this only as an export workaround.

## Visual character

The live document is a compact product UI system. Frequent colors include cyan
`#15C5CE`, dark text `#1F1F1F`/`#4B4B4B`, neutral `#8E8E8E`, border `#E1E1E1`,
white, and error/accent `#FF8156`. Frequent control text is PingFang HK/SC around
16 px; the source also uses Source Han Sans CN and Roboto. Check font availability
before judging geometry.

## Offline lookup recipes

Read the small guide first. For exact selection, query:

```text
catalog.pages["    Input"].components
catalog.families where page == "    Input" and name == "Basic"
family.variants where name contains "Size=Medium, State=Default"
component.detail.propCandidates
```

The leading spaces in TapTap page names are part of the snapshot. Normalize them
only for user display, not for exact catalog access.

