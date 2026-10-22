"""Demo profile editing: one revision for the whole set, served with a strong ETag."""
import asyncio
import hashlib
import json

from backend.domain import RuleError


class ProfileService:
    def __init__(self, repository, audiences):
        self.repository, self.audiences = repository, audiences

    async def _check_options(self, profiles):
        """Each selection must name a layer of the default template and one of its options."""
        config = (await asyncio.to_thread(self.audiences.template, 'default'))['config']
        layers = {layer.id: {option.id for option in layer.options} for layer in config.layers}
        for profile in profiles:
            for layer, option in profile['selections'].items():
                if option not in layers.get(layer, ()):
                    raise RuleError('unknown_audience_option', f"Profile {profile['id']}: {layer} '{option}' "
                                    'is not an option of the default audience template.', 422)

    async def document(self):
        revision, profiles = await asyncio.to_thread(self.repository.read)
        body = {'revision': revision, 'profiles': profiles}
        return body, '"' + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() + '"'

    async def replace(self, profiles, expected_revision=None, if_match=None):
        """Optimistic: `expected_revision`, or the ETag from `document` as If-Match."""
        await self._check_options(profiles)
        if expected_revision is None:
            current, etag = await self.document()
            if if_match is None:
                raise RuleError('revision_required', 'Send expected_revision or If-Match', 428)
            if if_match.strip().removeprefix('W/') != etag:
                raise RuleError('profiles_revision_conflict', 'Reload the profiles before saving', 409)
            expected_revision = current['revision']
        await asyncio.to_thread(self.repository.replace, profiles, expected_revision)
        return (await self.document())[0]
