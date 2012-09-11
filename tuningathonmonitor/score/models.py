from django.db import models

# Create your models here.
class Score(models.Model):
    ip = models.IPAddressField()
    score = models.FloatField()
    datetime = models.DateTimeField(auto_now=True)
