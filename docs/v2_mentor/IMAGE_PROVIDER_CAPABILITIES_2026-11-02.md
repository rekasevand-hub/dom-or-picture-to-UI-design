# Image Provider Capability Record

Date: 2026-11-02

Service: ACCTOKEN

Public documentation:

- https://www.acctoken.com/story
- https://www.acctoken.com/pricing

The public documentation identifies the OpenAI-compatible base URL
`https://www.acctoken.com/v1` and lists available model names. It does not
document image-edit mask semantics or vision-image pixel limits. The facts below
therefore combine repository configuration with controlled synthetic probes.
No API key or authorization header is recorded here.

## Current Production Configuration

| Field | Observed value |
| --- | --- |
| Vision base URL | `https://www.acctoken.com/v1` |
| Vision model | `qwen3-vl-plus` |
| Vision key configured | yes |
| Vision timeout | 600 seconds |
| Vision byte guard | 26,214,400 bytes |
| Text model | `deepseek-v4.1-flash` |
| Image generation base URL | not configured |
| Image generation key | not configured |
| Image generation model default | `gpt-image-1` |

The production Grounding pipeline currently sends image understanding requests
to `POST /v1/chat/completions`. It has no active image-generation
configuration. Therefore production currently cannot claim reference editing or
mask repair.

The separate Image To Slice benchmark instance was configured with:

- vision model: `qwen3-vl-plus`
- image generation and inpaint model: `seedream-5.0-flash`
- base URL: `https://www.acctoken.com/v1`

## Model Catalog

The authenticated `/v1/models` response contained 77 model ids. Relevant ids
included:

- `qwen3-vl-plus`
- `seedream-5.0-flash`
- `seedream-5.0-pro`
- `seedream-5.0-pro-layers`
- `qwen-image-2.0`
- `qwen-image-3.0-pro`
- `gpt-image-2.5`
- `image-cutout`

The catalog confirms model availability only. It does not prove endpoint
parameters or mask semantics.

## Sanitized Vision Request

```http
POST https://www.acctoken.com/v1/chat/completions
Content-Type: application/json
Authorization: Bearer <redacted>
```

```json
{
  "model": "qwen3-vl-plus",
  "temperature": 0,
  "response_format": {"type": "json_object"},
  "messages": [
    {"role": "system", "content": "Return JSON only."},
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "<capability-probe prompt>"},
        {
          "type": "image_url",
          "image_url": {"url": "data:image/png;base64,<redacted-image>"}
        }
      ]
    }
  ]
}
```

The image is actually embedded in the user message and sent to the model.

## Sanitized Reference Edit Request

```http
POST https://www.acctoken.com/v1/images/edits
Content-Type: multipart/form-data
Authorization: Bearer <redacted>
```

```text
model=seedream-5.0-flash
prompt=Change only the red square to blue...
size=1024x1024
quality=high
output_format=png
background=opaque
n=1
image[]=<reference-image-png>
```

Observed result: HTTP 200, one output image, 10.8 seconds. The center became
blue while the outside remained white, so the reference image participated in
the result rather than being replaced by a text-only generation.

## Sanitized Native Mask Request

```http
POST https://www.acctoken.com/v1/images/edits
Content-Type: multipart/form-data
Authorization: Bearer <redacted>
```

```text
model=seedream-5.0-flash
prompt=Reconstruct only the selected region...
size=1024x1024
quality=high
output_format=png
n=1
image[]=<source-image-png>
mask=<aligned-mask-png>
```

Observed result: HTTP 200, one output image, 6.7 seconds. The response provider
metadata reported `maskMode=native-mask`. The selected center changed to blue
while pixels outside the selection remained white.

Mask representation used by the Image To Slice adapter:

- source and mask are resized to the same output size;
- the selected/editable region is transparent in the native mask;
- non-selected/context regions are opaque white;
- RGB channels are white;
- alpha is `255 - selection`, so white selection becomes alpha 0.

This is the OpenAI-compatible mask convention: transparent pixels are edited,
opaque pixels are protected.

## Semantic Mask Fallback

The adapter also implements a non-native fallback:

- image 1: source image with selected pixels made transparent;
- image 2: grayscale selection mask;
- both files are sent through repeated `image[]` fields;
- no native `mask` field is used.

The fallback is not equivalent to native mask editing and cannot guarantee seam
quality. It should be marked as `semantic-reference-fallback`.

## Size Results

### Generic Reference Edit

- `256x256` failed with provider error: image area must be at least 921,600 pixels.
- `1024x1024` succeeded.

Generic edit requests preserve requested aspect dimensions for non-OpenAI host
URLs, clamped by the local adapter to `256..4096`. Provider constraints can be
stricter than that local clamp.

### Native Inpaint

The inpaint adapter snaps to one of:

- `1024x1024`
- `1536x1024`
- `1024x1536`

For a 256x256 source it prepared and successfully returned a 1024x1024 edit.

## Vision Input Probes

All probes used `qwen3-vl-plus`, synthetic PNGs, temperature 0 and the same
request structure.

| Input | Markers | Result | Image tokens |
| --- | --- | --- | ---: |
| 1024x1024 | 28px, four positions | all four labels read | 1,026 |
| 2048x1024 | 28px, four positions | all four labels read | 2,050 |
| 2544x6156 | 28px, top/middle/bottom/right | all four labels read | 2,498 |
| 2544x6156 | 12/16/20/24/28px at top/middle/bottom | all 15 labels read | 2,498 |
| 8192x1024 | 12px at left/middle/right and bottom | all five marker regions read; one label lost a letter | 2,433 |

Observed facts:

- the endpoint accepted both a very wide image and a 6,156-pixel-tall image;
- no request was rejected for exceeding a documented 4096-pixel dimension;
- small text remained readable in these synthetic probes;
- image-token counts stayed near 2,500 even when the source dimensions grew.

The token counts strongly suggest an internal fixed visual-token budget or
scale/tile strategy. They do not prove that the model reads every source pixel
at native resolution. The maximum native-resolution input, exact preprocessing,
and small-text threshold remain unknown.

Therefore:

- `4096px` is not a validated provider boundary;
- application-level width/height rejection should be removed;
- long images should still use a global overview plus overlapping detail tiles;
- a successful request is not evidence of native-resolution processing.

## Remaining Questions

1. Does ACCTOKEN document the vision model's actual visual-token budget and
   preprocessing resize rule? The public documentation does not.
2. Are mask semantics and minimum image area stable for all image models, or
   only the tested `seedream-5.0-flash` version?

These are documentation and provider-contract questions. They no longer block
the Python implementation because the adapter can record tested behavior,
enforce a minimum 1024x1024 preparation size for inpainting, and fall back
explicitly when the provider rejects masks.
