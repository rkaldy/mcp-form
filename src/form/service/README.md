# ImageService

`ImageService` performs JPEG transforms locally with Pillow and stores bytes in
R2. Obtain it in FastAPI with `Depends(get_image_service)` from
`form.service.dependencies`, or construct it with an R2 bucket binding.

`normalize` and `crop` are synchronous; `save`, `load` and `delete` are asynchronous:

- `normalize(image: bytes) -> bytes`: apply EXIF orientation and return an upright
  JPEG without orientation metadata.
- `crop(image: bytes, bounding_box: BoundingBox) -> bytes`: crop in the supplied
  image's coordinates. Normalize camera photos before extracting field coordinates
  and cropping. The bottom-right corner is exclusive. Partially overlapping boxes
  are clipped; empty, reversed and nonintersecting boxes raise `UserInputError`.
- `save(image_id: UUID, image: bytes)`: store the supplied bytes unchanged under
  the UUID's canonical string.
- `load(image_id: UUID) -> bytes`: return stored bytes unchanged; missing objects
  raise `FileNotFoundError`.
- `delete(image_id: UUID)`: delete the stored image under the UUID's canonical string.

For example, normalize a photo, send the normalized bytes to the LLM, and crop
those same bytes using the returned bounding boxes. Saving does not implicitly
normalize, and transforms do not access R2.

Pillow is constrained to the 12.2 series supported by the project's Pyodide
runtime. All transforms run synchronously on in-memory buffers without threads.

## R2 environments

`wrangler.jsonc` binds `FORM_IMAGES` to `form-images` with `remote: false`.
`make dev` uses local Wrangler storage, persisted under `.wrangler/state/`.
A deployed Worker uses the actual Cloudflare bucket; `remote: false` only applies
to development. Create `form-images` in the target Cloudflare account before
deploying. No Cloudflare Images binding is required.

See [Cloudflare R2 local development](https://developers.cloudflare.com/r2/api/workers/workers-api-usage/).
