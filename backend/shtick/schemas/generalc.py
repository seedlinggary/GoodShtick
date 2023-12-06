from backend.shtick.modals.generalc import Generalc
from config import ma



class GeneralcSchema(ma.Schema):
    class Meta:
        model = Generalc
        fields = ('id','name')
                # include_fk = True
generalc_schema = GeneralcSchema()
generalcs_schema = GeneralcSchema(many=True)