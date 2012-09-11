import threading
import time
import uuid
import urllib
import urllib2
import cookielib
import re
from subprocess import Popen, PIPE, STDOUT

CONCURRENCY = 10
MEASUREMENT = 10
TIMEOUT     = 10

HTTP_LOAD = '/home/ec2-user/bin/http_load'
URL_FILE  = '/home/ec2-user/etc/urls'

USER     = 'tuningathon'
EMAIL    = 'tuningathon@zero-start.jp'
GET_PATH  = '/basercms/index.php/tuningathon/archives/1'
POST_PATH = '/basercms/index.php/blog/blog_comments/add/2/3'

PARAM                                    = dict()
PARAM['_method']                         = 'GET'
PARAM['data[_Token][key]']               = ''
PARAM['data[_Token][fields]']            = ''
PARAM['data[BlogComment][name]']         = USER
PARAM['data[BlogComment][email]']        = EMAIL
PARAM['data[BlogComment][url]']          = ''
PARAM['data[BlogComment][message]']      = ''
PARAM['data[BlogComment][auth_captcha]'] = ''
PARAM_RANDOM_KEY = 'data[BlogComment][message]'

SCORE_POST_URL    = 'http://127.0.0.1:8000/score/post/'
SCORE_POST_SECRET = ''
SCORE_POST_PARAM  = dict()

class Score(object):

  def __init__(self):
    self._score = dict()

  def checker_result(self,elapsed,post,get_ok,get_error):
    self._score['checker_elapsed']   = float(elapsed)
    self._score['checker_post']      = float(post)
    self._score['checker_get_ok']    = float(get_ok)
    self._score['checker_get_error'] = float(get_error)
    self._score['checker_get_total'] = float(get_ok + get_error)
    self._score['checker_ok_rate']   = float(get_ok) / float(get_ok + get_error)

  def loader_result(self,elapsed,get_ok,get_error):
    self._score['loader_elapsed']   = float(elapsed)
    self._score['loader_get_ok']    = float(get_ok)
    self._score['loader_get_error'] = float(get_error)

  def compute(self):
    s = self._score.copy()

    if s['checker_elapsed']:
      checker_score = s['checker_post'] / s['checker_elapsed'] * 10
    else:
      checker_score = 0
    if s['loader_elapsed']:
      loader_score = s['loader_get_ok'] / s['loader_elapsed'] / 10
    else:
      loader_score = 0

    score = (checker_score + loader_score) * s['checker_ok_rate'] * s['checker_ok_rate']

    return score

  def post(self, ip, score, secret):
    SCORE_POST_PARAM['ip']     = ip
    SCORE_POST_PARAM['score']  = score
    SCORE_POST_PARAM['secret'] = secret

    p = urllib.urlencode(SCORE_POST_PARAM)

    urllib.urlopen(SCORE_POST_URL, p)

class CheckerThread(object):

  def __init__(self, host, measurement):
    self._host = host
    self._measurement = float(measurement)
    self._cond = threading.Condition(threading.Lock())
    self._thread = threading.Thread(target=self._run)
    self._thread.daemon = True
    self._value = None

    cj = cookielib.CookieJar()
    opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj))
    opener.addheaders = [('User-Agent','Mozilla/5.0 (Windows; U; Windows NT 5.1; ja; rv:1.9.0.1)')]

    self._opener = opener

  def _run(self):
    value = tuple()

    try:
      start_time = time.time()
      random_text = str()
      ok_count = 0
      error_count = 0
      post_count = 0
      loop = 0

      # if not below, first post may fail
      self.get_url(None)

      while True:
        if loop % 2:
          if self.get_url(random_text):
            ok_count += 1
          else:
            error_count += 1

          elapsed = time.time() - start_time
          if elapsed > self._measurement:
            break
        else:
          random_text = self.post_url()
          post_count += 1
        
        loop += 1

      value = (elapsed, post_count, ok_count, error_count)
      
    except Exception, e:
      import traceback
      print traceback.format_exc()
      value = e
      
    finally:
      self._cond.acquire()
      try:
        self._value = value
        self._cond.notify()
      finally:
        self._cond.release()
  
  def get_url(self, random_text):
    try:
      url = 'http://%s%s' % (self._host, GET_PATH)
      r = self._opener.open(url,None,TIMEOUT)
    except Exception:
      return False

    if not random_text:
      return False

    content = r.read()
    if random_text not in content:
      return False

    return True
  
  def post_url(self):
    random_text = uuid.uuid4().hex
    PARAM[PARAM_RANDOM_KEY] = random_text

    p = urllib.urlencode(PARAM)

    url = 'http://%s%s' % (self._host, POST_PATH)
    try:
      self._opener.open(url,p,TIMEOUT)
    except Exception:
      pass
    return random_text
  
  def start(self):
    self._thread.start()
  
  def wait(self, timeout=None):
    self._cond.acquire()
    try:
      if self._value is None:
        self._cond.wait(timeout or 60)
    finally:
      self._cond.release()
  
  def get(self, timeout=None):
    self.wait(timeout)

    if isinstance(self._value, tuple):
      return self._value

    raise

class Loader(object):

  def __init__(self, host, measurement, concurrency):
    self._host = host
    self._concurrency = concurrency
    self._measurement = measurement
    self._pattern_fetch = '^\d+ fetches, \d+ max parallel, [^ ]+ bytes, in ([\d\.]+) seconds$'
    self._pattern_status = '^  code (\d+) -- (\d+)$'

  def start(self):
    self.init_url_file()

    score = self.run_http_load()

    return score

  def init_url_file(self):
    f = open(URL_FILE, 'wb')

    try:
      url = 'http://%s%s' % (self._host, GET_PATH)
      f.write(url)
    finally:
      f.close()

  def run_http_load(self):
    args = [HTTP_LOAD, '-parallel', str(self._concurrency - 1), '-seconds', str(self._measurement), URL_FILE]
    p = Popen(args, stdout=PIPE, stderr=STDOUT)

    output = list()
  
    try:
      for line in p.stdout.readlines():
        line = line.rstrip()
        output.append(line)
      p.wait()
    except:
      p.terminate()
      raise

    re_fetch = re.compile(self._pattern_fetch)
    re_status = re.compile(self._pattern_status)

    elapsed = 0
    ok_count = 0
    error_count = 0

    for line in output:
      m = re_fetch.search(line)
      if m:
        elapsed = float(m.group(1))
        continue

      m = re_status.search(line)
      if m:
        code = int(m.group(1))
        count = int(m.group(2))

        if code == 200:
          ok_count += count
        else:
          error_count += count

    return elapsed, ok_count, error_count

def main():
  from optparse import OptionParser
  
  parser = OptionParser()
  parser.add_option('-c', type='int', dest='concurrency', default=CONCURRENCY, help='concurrency number')
  parser.add_option('-s', type='int', dest='measurement', default=MEASUREMENT, help='measurement time')
  parser.add_option('-p', type='string', dest='post_secret', default=SCORE_POST_SECRET, help='score post secret')
  options, args = parser.parse_args()

  if len(args) != 1:
      parser.print_help()
      return

  host = args[0]
  checker = CheckerThread(host, options.measurement)
  loader = Loader(host, options.measurement, options.concurrency)

  try:
    checker.start()
    (loader_elapsed, loader_get_ok, loader_get_error) = loader.start()
    (checker_elapsed, checker_post, checker_get_ok, checker_get_error) = checker.get()

    score = Score()
    score.checker_result(checker_elapsed, checker_post, checker_get_ok, checker_get_error)
    score.loader_result(loader_elapsed, loader_get_ok, loader_get_error)

    s = score.compute()

    if options.post_secret:
      print '%s %s' % (host,s)
      score.post(host, s, options.post_secret)
    else:
      print s
    
  except Exception, e:
    print e
    import traceback
    print traceback.format_exc()
  except KeyboardInterrupt:
    print 'KeyboardInterrupt'

if __name__ == '__main__':
    main()
