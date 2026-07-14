from datetime import datetime

from marshmallow import Schema, fields

from upload import get_public_url
from backend.shtick.schemas.shtick import UserPublicSchema


class LikeCountMixin:
    """Shared by every Hock schema with a `likes` relationship + a
    viewer-scoped `liked_by_me` (reads `self.context['user_id']`)."""

    def get_like_count(self, obj):
        return len(obj.likes)

    def get_liked_by_me(self, obj):
        uid = self.context.get('user_id')
        if not uid:
            return False
        return any(l.user_id == uid for l in obj.likes)


class ImageUrlMixin:
    """Shared by every Hock schema with an optional `image` filename."""

    def get_image_url(self, obj):
        try:
            return get_public_url(obj.image) if obj.image else None
        except Exception:
            return None


class HockCommentSchema(LikeCountMixin, Schema):
    """A single comment, with its reply subtree nested recursively.

    `replies` is rendered via a Method field so the same schema (and its
    request-scoped `context`, which carries the viewer's public_id for
    `liked_by_me`) recurses to arbitrary depth rather than flattening after
    one or two levels.
    """
    id = fields.Int()
    text = fields.Str()
    hock_post_id = fields.Int()
    parent_comment_id = fields.Int(allow_none=True)
    user_id = fields.Str()
    user = fields.Nested(UserPublicSchema)
    pub_date = fields.DateTime()
    edited_at = fields.DateTime(allow_none=True)
    approved_to_publish = fields.Bool()
    like_count = fields.Method('get_like_count')
    liked_by_me = fields.Method('get_liked_by_me')
    reply_count = fields.Method('get_reply_count')
    replies = fields.Method('get_replies')

    def _visible(self, comments):
        if self.context.get('is_boss'):
            return comments
        return [c for c in comments if c.approved_to_publish]

    def get_reply_count(self, obj):
        return len(self._visible(obj.replies))

    def get_replies(self, obj):
        children = sorted(self._visible(obj.replies), key=lambda c: c.pub_date or datetime.min)
        child_schema = HockCommentSchema(many=True)
        child_schema.context = self.context
        return child_schema.dump(children)


class HockPostSchema(ImageUrlMixin, LikeCountMixin, Schema):
    """Full post — includes the nested comment tree (used on the detail page)."""
    id = fields.Int()
    title = fields.Str()
    body = fields.Str()
    image = fields.Str(allow_none=True)
    image_url = fields.Method('get_image_url')
    user_id = fields.Str()
    user = fields.Nested(UserPublicSchema)
    pub_date = fields.DateTime()
    edited_at = fields.DateTime(allow_none=True)
    approved_to_publish = fields.Bool()
    approved_by = fields.Str(allow_none=True)
    like_count = fields.Method('get_like_count')
    comment_count = fields.Method('get_comment_count')
    liked_by_me = fields.Method('get_liked_by_me')
    comments = fields.Method('get_comments')

    def _visible_comments(self, obj):
        if self.context.get('is_boss'):
            return obj.comments
        return [c for c in obj.comments if c.approved_to_publish]

    def get_comment_count(self, obj):
        # Total across the whole thread (the `comments` relationship is every
        # comment on the post, replies included), so the feed count matches
        # what a reader actually sees on the detail page.
        return len(self._visible_comments(obj))

    def get_comments(self, obj):
        top_level = sorted(
            (c for c in self._visible_comments(obj) if c.parent_comment_id is None),
            key=lambda c: c.pub_date or datetime.min,
        )
        child_schema = HockCommentSchema(many=True)
        child_schema.context = self.context
        return child_schema.dump(top_level)


class HockPostCardSchema(ImageUrlMixin, LikeCountMixin, Schema):
    """Lean post card for the feed list — no comment tree, just the counts."""
    id = fields.Int()
    title = fields.Str()
    body = fields.Str()
    image = fields.Str(allow_none=True)
    image_url = fields.Method('get_image_url')
    user_id = fields.Str()
    user = fields.Nested(UserPublicSchema)
    pub_date = fields.DateTime()
    edited_at = fields.DateTime(allow_none=True)
    approved_to_publish = fields.Bool()
    approved_by = fields.Str(allow_none=True)
    like_count = fields.Method('get_like_count')
    comment_count = fields.Method('get_comment_count')
    liked_by_me = fields.Method('get_liked_by_me')

    def get_comment_count(self, obj):
        if self.context.get('is_boss'):
            return len(obj.comments)
        return len([c for c in obj.comments if c.approved_to_publish])


def make_post_schema(current_user=None, many=False, card=False):
    """Build a post schema bound to the viewer (for liked_by_me').

    marshmallow 4 removed the `context=` constructor kwarg present in
    marshmallow 3 — `context` is still a plain instance attribute, it just
    has to be set after construction rather than passed in.
    """
    ctx = {
        'user_id': current_user.public_id if current_user else None,
        'is_boss': bool(current_user and current_user.is_boss),
    }
    cls = HockPostCardSchema if card else HockPostSchema
    schema = cls(many=many)
    schema.context = ctx
    return schema


def make_comment_schema(current_user=None, many=False):
    ctx = {
        'user_id': current_user.public_id if current_user else None,
        'is_boss': bool(current_user and current_user.is_boss),
    }
    schema = HockCommentSchema(many=many)
    schema.context = ctx
    return schema
