from django.shortcuts import render_to_response
from django.template.context import RequestContext
from django.http import HttpResponse, HttpResponseRedirect
from django.contrib.auth.views import login
from django.contrib.auth.decorators import login_required
from django_redis import get_redis_connection
import requests, re, ast, random, HTMLParser
from core.models import UserMetrics, ColleagueGraph
from django.core.exceptions import ObjectDoesNotExist
from core.forms import SuggestionForm, ResultForm

def custom_login(request):
    if request.user.is_authenticated():
        return HttpResponseRedirect('/')
    else:
        return login(request)


@login_required()
def cards(request):
    redis_con = get_redis_connection("default")
    # Unique Set per Network
    if request.user.email:
        network = request.user.email.split('@')[1]
    else:
        network = 'default'

    if redis_con.exists(network + '_users'):
        print "Cache Retrieved"
    else:
        print "Cache Loaded"
        users = []
        social = request.user.social_auth.get(provider='yammer')
        access_token = social.extra_data['access_token']

        page = 1

        while True:
            response = requests.get(
                'https://www.yammer.com/api/v1/users.json?page=%d' % page,
                headers = {'Authorization': 'Bearer %s' % access_token['token']}
            )
            if response.json() == []:
                break
            users.extend(response.json())
            page += 1

        pattern = re.compile('.+no_photo.png$')  # Filters out users with no photo
        for user in users:
            if not pattern.match(user['mugshot_url']):
                redis_con.sadd(user['network_name'] + '_users', {
                    'id': user['id'],
                    'name': user['full_name'],
                    'mugshot': user['mugshot_url_template'],
                    'user_url': user['web_url'],
                    'network': user['network_name'],
                })
        redis_con.expire(network + '_users', 43200)  # Redis cache expiration set to 12hrs(43200s)

    user_round_matrix = [four_random_cards(redis_con, network) for x in range(5)]
    answer = random.choice(user_round_matrix[0])


    context = RequestContext(request, {'cards': user_round_matrix, 'answer': answer,
                                       'round': 0, 'score': 0})
    return render_to_response('game.html', context_instance=context)


@login_required
def next_round(request):
    round = int(request.POST['round'])
    score = int(request.POST['score'])
    card_index = int(request.POST['cardIndex'])

    card_matrix = HTMLParser.HTMLParser().unescape(request.POST['matrix'])
    card_matrix = ast.literal_eval(card_matrix)

    # Sets the Winner of the round to the cardMatrix
    update_results_list(card_matrix, card_index, round)

    # Prepares data for next round
    round += 1
    answer = random.choice(card_matrix[round])
    context = RequestContext(request, {'cards': card_matrix, 'round': round, 'answer': answer,
                                       'score': score, 'resultsForm': ResultForm()})

    return render_to_response('cards.html', context_instance=context)


@login_required
def results(request):
    try:
        metric = UserMetrics.objects.get(user=request.user)
    except ObjectDoesNotExist:
        # This is here purely for backwards compatibility TODO remember to delete this line later
        metric = UserMetrics.objects.create(user=request.user).save()

    if request.method == 'POST':
        form = ResultForm(request.POST)
        if form.is_valid():
            metric.times_won = form.cleaned_data['score']
            metric.save()

            results = ast.literal_eval(HTMLParser.HTMLParser().unescape(form.cleaned_data['results']))
            card_index = form.cleaned_data['cardIndex']

            update_results_list(results, card_index, 4)  # 4 representing the last round (zero-based)
            save_metric_results(results, request.user)

            return metrics(request, form.cleaned_data['score'], results)


# Helper Functions


def metrics(request, score, matrix):
    metrics = ColleagueGraph.objects.filter(user=request.user)
    names = ''
    known = []
    imgs = ''
    for metric in metrics:
        names += str(metric.name) + ';'
        known.append(metric.times_correct)
        imgs += str(metric.img_url) + ';'


    gMetrics = globallyKnownColleagues()
    gNames = ''
    gKnown = []
    gImgs = ''
    for metric in gMetrics:
        gNames += str(metric.name) + ';'
        gKnown.append(metric.times_correct)
        gImgs += str(metric.img_url) + ';'

    lowest_ten_colleagues = (ColleagueGraph.objects.filter(user=request.user).order_by('times_correct'))[:5]
    lowest_names = ''
    lowest_known = []
    lowest_imgs = ''
    for metric in lowest_ten_colleagues:
        lowest_names += str(metric.name) + ';'
        lowest_known.append(metric.times_correct)
        lowest_imgs += ((str(metric.img_url) + ';').replace("{width}", "70")).replace("{height}", "70")

    print (lowest_names)

    context = RequestContext(request, {'names': names, 'known': known,'mugs': imgs, 'score': score, 'cards': matrix,
                                       'gNames': gNames, 'gKnown': gKnown, 'mugs': gImgs, 'lowest_names': lowest_names,
                                       'lowest_known': lowest_known, 'lowest_mugs': lowest_imgs
                                       })
    return render_to_response('results.html', context_instance=context)


def save_metric_results(results, user):
    for result in results:
        if result:
            try:
                metric = ColleagueGraph.objects.get(user=user, yammer_id=result['id'])
                metric.times_correct += 1
            except ObjectDoesNotExist:
                metric = ColleagueGraph.objects.create(user=user, yammer_id=result['id'],
                                                       name=result['name'], img_url=result['mugshot'],
                                                       times_correct=1)
            finally:
                metric.save()


def update_results_list(card_matrix, card_index, round):
    if card_index > -1:
        card_matrix[round] = card_matrix[round][card_index]
    else:
        card_matrix[round][card_index]['wrong'] = True
        card_matrix[round] = card_matrix[round][card_index]

    return card_matrix


def four_random_cards(redis_con, network):
    users = []
    while len(users) < 4:
        tmp = ast.literal_eval(redis_con.srandmember(network + '_users'))
        if tmp not in users:
            users.append(tmp)
    return users


def globallyKnownColleagues():
    top_scores = (ColleagueGraph.objects.order_by('-times_correct').values_list('times_correct', flat=True).distinct())
    top_10_known_colleagues = (ColleagueGraph.objects.order_by('-times_correct')
                               .filter(times_correct__in=top_scores[:10]))[:10]

    return top_10_known_colleagues



def ajax_suggestion(request):
    if request.method == 'POST' and request.is_ajax():
        form = SuggestionForm(request.POST)
        if form.is_valid():
            form.save(commit=True)
            return HttpResponse("Thank you for your suggestion!")
        else:
            return HttpResponse("Invalid Data!")

    else:
        return HttpResponse('Service unavailable')

