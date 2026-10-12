from config import db
from datetime import datetime


class BusinessQuestion(db.Model):
    """'Ask a question' without needing WhatsApp/a phone number. Answered
    questions double as a small public FAQ on the profile -- later visitors
    with the same question benefit, not just the original asker."""
    __tablename__ = 'business_question'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True, index=True)
    asker_name = db.Column(db.String(150), nullable=False)
    asker_email = db.Column(db.String(150), nullable=True)

    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=True)
    answered_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    business = db.relationship('Business', backref=db.backref('questions', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', foreign_keys=[user_id])

    def __init__(self, business_id, asker_name, question, user_id=None, asker_email=None):
        self.business_id = business_id
        self.user_id = user_id
        self.asker_name = asker_name
        self.asker_email = asker_email
        self.question = question

    @property
    def is_answered(self):
        return self.answer is not None

    def __repr__(self):
        return f'BusinessQuestion({self.id}) business={self.business_id} answered={self.is_answered}'
