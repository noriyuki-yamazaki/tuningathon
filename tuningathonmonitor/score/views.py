# Create your views here.
from django.http import HttpResponse
from django.shortcuts import render_to_response
from tuningathonmonitor import settings
from score.models import Score

def index(request):
    ranking = Score.objects.raw("""
        SELECT id AS id,ip AS ip,max(score) AS score,datetime AS datetime FROM score_score
        GROUP BY ip
        ORDER BY score DESC""")

    return render_to_response('score/index.html', {'ranking':ranking})

def post(request):
    p = request.REQUEST.copy()

    try:
        secret = p['secret']
        ip     = p['ip']
        score  = p['score']
    except:
        return HttpResponse("invalid args")

    if secret == settings.SCORE_POST_SECRET:
        q = Score(ip=ip, score=score)
        q.save()
        return HttpResponse("posted %s %s" % (ip,score))
    else:
        return HttpResponse("invalid secret")
        

