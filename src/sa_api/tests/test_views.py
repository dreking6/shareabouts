from django.test import TestCase
from django.test.client import Client
from django.test.client import RequestFactory
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from djangorestframework.response import ErrorResponse
from mock import patch
from nose.tools import istest, assert_equal, assert_in, assert_raises
from ..models import DataSet, Place, Submission, SubmissionSet
from ..models import SubmittedThing, Activity
from ..views import SubmissionCollectionView
from ..views import raise_error_if_not_authenticated
from ..views import ApiKeyCollectionView
import json
import mock


class TestAuthFunctions(object):

    class DummyView(object):

        def post(self, request):
            raise_error_if_not_authenticated(self, request)
            return 'ok'

    @istest
    def test_auth_required_without_a_user(self):
        request = RequestFactory().post('/foo')
        assert_raises(ErrorResponse, self.DummyView().post, request)

    @istest
    def test_auth_required_with_logged_out_user(self):
        request = RequestFactory().post('/foo')
        request.user = mock.Mock(**{'is_authenticated.return_value': False})
        assert_raises(ErrorResponse, self.DummyView().post, request)

    @istest
    def test_auth_required_with_logged_in_user(self):
        request = RequestFactory().post('/foo')
        request.user = mock.Mock(**{'is_authenticated.return_value': True,
                                    'username': 'bob'})
        # No exceptions, don't care about return value.
        self.DummyView().post(request)

    @istest
    def test_isownerorsuperuser__anonymous_not_allowed(self):
        user = mock.Mock(**{'is_authenticated.return_value': False,
                            'is_superuser': False})
        view = mock.Mock(request=RequestFactory().get(''))
        from ..views import IsOwnerOrSuperuser
        assert_raises(ErrorResponse,
                      IsOwnerOrSuperuser(view).check_permission, user)

    @istest
    def test_isownerorsuperuser__wrong_user_not_allowed(self):
        view = mock.Mock(username='bob',
                         request=RequestFactory().get(''))
        user = mock.Mock(is_superuser=False, username='not bob')
        from ..views import IsOwnerOrSuperuser
        assert_raises(ErrorResponse,
                      IsOwnerOrSuperuser(view).check_permission, user)

    @istest
    def test_isownerorsuperuser__superuser_is_allowed(self):
        user = mock.Mock(is_superuser=True)
        view = mock.Mock(request=RequestFactory().get(''))

        from ..views import IsOwnerOrSuperuser
        # No exceptions == good.
        IsOwnerOrSuperuser(view).check_permission(user)

    @istest
    def test_isownerorsuperuser__owner_is_allowed(self):
        view = mock.Mock(username='bob',
                         request=RequestFactory().get(''))
        user = mock.Mock(is_superuser=False, username='bob')
        from ..views import IsOwnerOrSuperuser
        # If not exceptions, we're OK.
        IsOwnerOrSuperuser(view).check_permission(user)


class TestDataSetCollectionView(TestCase):

    @istest
    def post_creates_an_api_key(self):
        from ..apikey.models import ApiKey
        DataSet.objects.all().delete()
        ApiKey.objects.all().delete()
        User.objects.all().delete()

        # TODO: mock the models?
        user = User.objects.create(username='bob')

        kwargs = {'owner__username': user.username}
        url = reverse('dataset_collection_by_user', kwargs=kwargs)
        data = {
            'display_name': 'Test DataSet',
            'slug': 'test-dataset',
        }

        from ..views import DataSetCollectionView

        request = RequestFactory().post(url, data=json.dumps(data),
                                        content_type='application/json')
        request.user = user
        view = DataSetCollectionView().as_view()
        # Have to pass kwargs explicitly if not using
        # urlresolvers.resolve() etc.
        response = view(request, **kwargs)

        assert_equal(response.status_code, 201)
        assert_in(url + 'test-dataset', response.get('Location'))

        response_data = json.loads(response.content)
        assert_equal(response_data['display_name'], 'Test DataSet')
        assert_equal(response_data['slug'], 'test-dataset')


class TestDataSetInstanceView(TestCase):

    def setUp(self):
        DataSet.objects.all().delete()
        User.objects.all().delete()
        user = User.objects.create(username='bob')
        self.dataset = DataSet.objects.create(slug='dataset',
                                              display_name='dataset',
                                              owner=user)

    @istest
    def put_with_slug_gives_a_new_location(self):
        kwargs = dict(owner__username='bob', slug='dataset')
        url = reverse('dataset_instance_by_user', kwargs=kwargs)
        data = {'slug': 'new-name', 'display_name': 'dataset'}
        request = RequestFactory().put(url, data=json.dumps(data),
                                       content_type='application/json'
                                       )
        request.user = mock.Mock(**{'is_authenticated.return_value': True})
        from ..views import DataSetInstanceView
        view = DataSetInstanceView().as_view()
        response = view(request, **kwargs)
        assert_equal(response.status_code, 303)
        assert_in('/new-name', response['Location'])


class TestMakingAGetRequestToASubmissionTypeCollectionUrl (TestCase):

    @istest
    def should_call_view_with_place_id_and_submission_type_name(self):
        client = Client()

        with patch('sa_api.views.SubmissionCollectionView.get') as getter:
            client.get('/api/v1/places/1/comments/')
            args, kwargs = getter.call_args
            assert_equal(
                kwargs,
                {'place_id': u'1',
                 'submission_type': u'comments'}
            )

    @istest
    def should_return_a_list_of_submissions_of_the_type_for_the_place(self):
        User.objects.all().delete()
        DataSet.objects.all().delete()
        Place.objects.all().delete()
        Submission.objects.all().delete()
        SubmissionSet.objects.all().delete()

        owner = User.objects.create()
        dataset = DataSet.objects.create(slug='data', owner_id=owner.id)
        place = Place.objects.create(location='POINT(0 0)', dataset_id=dataset.id)
        comments = SubmissionSet.objects.create(place_id=place.id, submission_type='comments')
        Submission.objects.create(parent_id=comments.id, dataset_id=dataset.id)
        Submission.objects.create(parent_id=comments.id, dataset_id=dataset.id)

        request = RequestFactory().get('/places/%d/comments/' % place.id)
        view = SubmissionCollectionView.as_view()

        response = view(request, place_id=place.id,
                        submission_type='comments')
        data = json.loads(response.content)
        assert_equal(len(data), 2)


    @istest
    def should_return_an_empty_list_if_the_place_has_no_submissions_of_the_type(self):
        User.objects.all().delete()
        DataSet.objects.all().delete()
        Place.objects.all().delete()
        Submission.objects.all().delete()

        owner = User.objects.create()
        dataset = DataSet.objects.create(slug='data', owner_id=owner.id)
        place = Place.objects.create(location='POINT(0 0)', dataset_id=dataset.id)
        comments = SubmissionSet.objects.create(place_id=place.id, submission_type='comments')
        Submission.objects.create(parent_id=comments.id, dataset_id=dataset.id)
        Submission.objects.create(parent_id=comments.id, dataset_id=dataset.id)

        request = RequestFactory().get('/places/%d/votes/' % place.id)
        view = SubmissionCollectionView.as_view()

        response = view(request, place_id=place.id,
                        submission_type='votes')
        data = json.loads(response.content)
        assert_equal(len(data), 0)


class TestMakingAPostRequestToASubmissionTypeCollectionUrl (TestCase):

    @istest
    def should_create_a_new_submission_of_the_given_type_on_the_place(self):
        User.objects.all().delete()
        DataSet.objects.all().delete()
        Place.objects.all().delete()
        Submission.objects.all().delete()
        SubmissionSet.objects.all().delete()

        owner = User.objects.create()
        dataset = DataSet.objects.create(slug='data',
                                              owner_id=owner.id)
        place = Place.objects.create(location='POINT(0 0)',
                                          dataset_id=dataset.id)
        comments = SubmissionSet.objects.create(place_id=place.id, submission_type='comments')

        data = {
            'submitter_name': 'Mjumbe Poe',
            'age': 12,
            'comment': 'This is rad!',
        }
        request = RequestFactory().post('/places/%d/comments/' % place.id,
                                        data=json.dumps(data), content_type='application/json')
        request.user = mock.Mock(**{'is_authenticated.return_value': True})
        view = SubmissionCollectionView.as_view()

        response = view(request, place_id=place.id,
                        submission_type='comments')
        data = json.loads(response.content)
        #print response
        assert_equal(response.status_code, 201)
        assert_in('age', data)


class TestSubmissionInstanceAPI (TestCase):

    def setUp(self):
        User.objects.all().delete()
        DataSet.objects.all().delete()
        Place.objects.all().delete()
        Submission.objects.all().delete()
        SubmissionSet.objects.all().delete()

        self.owner = User.objects.create()
        self.dataset = DataSet.objects.create(slug='data',
                                              owner_id=self.owner.id)
        self.place = Place.objects.create(location='POINT(0 0)',
                                          dataset_id=self.dataset.id)
        self.comments = SubmissionSet.objects.create(place_id=self.place.id,
                                                submission_type='comments')
        self.submission = Submission.objects.create(parent_id=self.comments.id,
                                                    dataset_id=self.dataset.id)
        self.url = reverse('submission_instance',
                           kwargs=dict(place_id=self.place.id,
                                       pk=self.submission.id,
                                       submission_type='comments'))
        from ..views import SubmissionInstanceView
        self.view = SubmissionInstanceView.as_view()

    @istest
    def put_request_should_modify_instance(self):
        data = {
            'submitter_name': 'Paul Winkler',
            'age': 99,
            'comment': 'Get off my lawn!',
        }

        request = RequestFactory().put(self.url, data=json.dumps(data),
                                       content_type='application/json')
        request.user = mock.Mock(**{'is_authenticated.return_value': True})
        response = self.view(request, place_id=self.place.id,
                             pk=self.submission.id,
                             submission_type='comments')
        response_data = json.loads(response.content)
        assert_equal(response.status_code, 200)
        self.assertDictContainsSubset(data, response_data)

    @istest
    def delete_request_should_delete_submission(self):
        request = RequestFactory().delete(self.url)
        request.user = mock.Mock(**{'is_authenticated.return_value': True})
        response = self.view(request, place_id=self.place.id,
                             pk=self.submission.id,
                             submission_type='comments')

        assert_equal(response.status_code, 204)
        assert_equal(Submission.objects.all().count(), 0)

    @istest
    def submission_get_request_retrieves_data(self):
        self.submission.data = json.dumps({'animal': 'tree frog'})
        self.submission.save()
        request = RequestFactory().get(self.url)
        response = self.view(request, place_id=self.place.id,
                             pk=self.submission.id,
                             submission_type='comments')

        assert_equal(response.status_code, 200)
        data = json.loads(response.content)
        assert_equal(data['animal'], 'tree frog')


class TestActivityView(TestCase):

    def setUp(self):
        User.objects.all().delete()
        DataSet.objects.all().delete()
        Place.objects.all().delete()
        Submission.objects.all().delete()
        SubmittedThing.objects.all().delete()
        Activity.objects.all().delete()

        self.owner = User.objects.create(username='myuser')
        self.dataset = DataSet.objects.create(slug='data',
                                              owner_id=self.owner.id)
        self.visible_place = Place.objects.create(dataset_id=self.dataset.id, location='POINT (0 0)', visible=True)
        self.invisible_place = Place.objects.create(dataset_id=self.dataset.id, location='POINT (0 0)', visible=False)

        self.visible_set = SubmissionSet.objects.create(place_id=self.visible_place.id)
        self.invisible_set = SubmissionSet.objects.create(place_id=self.invisible_place.id)

        self.visible_submission = Submission.objects.create(dataset_id=self.dataset.id, parent_id=self.visible_set.id)
        self.invisible_submission = Submission.objects.create(dataset_id=self.dataset.id, parent_id=self.invisible_set.id)

        # Note this implicitly creates an Activity.
        visible_place_activity = Activity.objects.get(data_id=self.visible_place.id)
        visible_submission_activity = Activity.objects.get(data_id=self.visible_submission.id)

        self.activities = [
            visible_place_activity,
            visible_submission_activity,
            Activity.objects.create(data=self.visible_place, action='update'),
            Activity.objects.create(data=self.visible_place, action='delete'),
        ]

        kwargs = dict(data__dataset__owner__username=self.owner.username, data__dataset__slug='data')
        self.url = reverse('activity_collection_by_dataset', kwargs=kwargs)

        # This was here first and marked as deprecated, but above doesn't
        # work either.
        # self.url = reverse('activity_collection')

    @istest
    def get_queryset_no_params_returns_visible(self):
        from ..views import ActivityView
        view = ActivityView()
        view.request = RequestFactory().get(self.url)
        qs = view.get_queryset()
        self.assertEqual(qs.count(), len(self.activities))

    @istest
    def get_queryset_with_visible_all_returns_all(self):
        from ..views import ActivityView
        view = ActivityView()
        view.request = RequestFactory().get(self.url + '?visible=all')
        qs = view.get_queryset()
        self.assertEqual(qs.count(), 6)

    @istest
    def get_queryset_before(self):
        from ..views import ActivityView
        view = ActivityView()
        ids = sorted([a.id for a in self.activities])
        view.request = RequestFactory().get(self.url + '?before=%d' % ids[0])
        self.assertEqual(view.get_queryset().count(), 1)
        view.request = RequestFactory().get(self.url + '?before=%d' % ids[-1])
        self.assertEqual(view.get_queryset().count(), len(self.activities))

    @istest
    def get_queryset_after(self):
        from ..views import ActivityView
        view = ActivityView()
        ids = sorted([a.id for a in self.activities])
        view.request = RequestFactory().get(self.url + '?after=%d' % (ids[0] - 1))
        self.assertEqual(view.get_queryset().count(), 4)
        view.request = RequestFactory().get(self.url + '?after=%d' % ids[0])
        self.assertEqual(view.get_queryset().count(), 3)
        view.request = RequestFactory().get(self.url + '?after=%d' % ids[-1])
        self.assertEqual(view.get_queryset().count(), 0)

    @istest
    def get_with_limit(self):
        from ..views import ActivityView
        view = ActivityView()
        view.request = RequestFactory().get(self.url + '?limit')
        self.assertEqual(view.get(view.request).count(), len(self.activities))

        view.request = RequestFactory().get(self.url + '?limit=99')
        self.assertEqual(view.get(view.request).count(), len(self.activities))

        view.request = RequestFactory().get(self.url + '?limit=0')
        self.assertEqual(view.get(view.request).count(), 0)

        view.request = RequestFactory().get(self.url + '?limit=1')
        self.assertEqual(view.get(view.request).count(), 1)


class TestAbsUrlMixin (object):

    @istest
    def test_process_urls(self):
        data = {
            'url': '/foo/bar',
            'x': 'y',
            'children': [{'x': 'y', 'url': '/hello/cats'},
                         {'a': 'b', 'url': 'bye/../dogs'},
                         ]
        }
        from ..views import AbsUrlMixin
        aum = AbsUrlMixin()
        aum.request = RequestFactory().get('/path_is_irrelevant')
        aum.process_urls(data)
        assert_equal(data['url'], 'http://testserver/foo/bar')
        assert_equal(data['children'][0]['url'],
                     'http://testserver/hello/cats')
        assert_equal(data['children'][1]['url'],
                     'http://testserver/dogs')


class TestPlaceCollectionView(TestCase):

    def _cleanup(self):
        from sa_api import models
        from django.contrib.auth.models import User
        models.Submission.objects.all().delete()
        models.SubmissionSet.objects.all().delete()
        models.Place.objects.all().delete()
        models.DataSet.objects.all().delete()
        User.objects.all().delete()

    def setUp(self):
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    @istest
    def post_creates_a_place(self):
        from ..views import PlaceCollectionView, models
        view = PlaceCollectionView().as_view()
        # Need an existing DataSet.
        from django.contrib.auth.models import User
        user = User.objects.create(username='test-user')
        ds = models.DataSet.objects.create(owner=user, id=789,
                                           slug='stuff')
        #place = models.Place.objects.create(dataset=ds, id=123)
        uri_args = {
            'dataset__owner__username': user.username,
            'dataset__slug': ds.slug,
        }
        uri = reverse('place_collection_by_dataset', kwargs=uri_args)
        data = {'location': {'lat': 39.94494, 'lng': -75.06144},
                'description': 'hello', 'location_type': 'School',
                'name': 'Ward Melville HS',
                'submitter_name': 'Joe',
                }
        request = RequestFactory().post(uri, data=json.dumps(data),
                                        content_type='application/json')
        request.user = user
        # Ready to post. Verify there are no Places yet...
        assert_equal(models.Place.objects.count(), 0)

        response = view(request, **uri_args)

        # We got a Created status...
        assert_equal(response.status_code, 201)
        assert_in(uri, response.get('Location'))

        # And we have a place:
        assert_equal(models.Place.objects.count(), 1)


class TestApiKeyCollectionView(TestCase):

    def _cleanup(self):
        from sa_api import models
        from django.contrib.auth.models import User
        from sa_api.apikey.models import ApiKey
        models.DataSet.objects.all().delete()
        User.objects.all().delete()
        ApiKey.objects.all().delete()

    def setUp(self):
        self._cleanup()
        # Need an existing DataSet.
        user = User.objects.create(username='test-user')
        self.dataset = DataSet.objects.create(owner=user, id=789,
                                              slug='stuff')
        self.uri_args = {
            'datasets__owner__username': user.username,
            'datasets__slug': self.dataset.slug,
        }
        uri = reverse('api_key_collection_by_dataset',
                      kwargs=self.uri_args)
        self.request = RequestFactory().get(uri)
        self.view = ApiKeyCollectionView().as_view()

    def tearDown(self):
        self._cleanup()

    @istest
    def get__not_allowed_anonymous(self):
        self.request.user = mock.Mock(**{'is_authenticated.return_value': False,
                                         'is_superuser': False})
        response = self.view(self.request, **self.uri_args)
        assert_equal(response.status_code, 403)

    @istest
    def get_is_allowed_if_admin(self):
        self.request.user = mock.Mock(**{'is_authenticated.return_value': True,
                                         'is_superuser': True})
        response = self.view(self.request, **self.uri_args)
        assert_equal(response.status_code, 200)

    @istest
    def get_is_allowed_if_owner(self):
        self.request.user = self.dataset.owner
        response = self.view(self.request, **self.uri_args)
        assert_equal(response.status_code, 200)

    @istest
    def get_not_allowed_with_api_key(self):
        from ..apikey.auth import KEY_HEADER
        self.request.META[KEY_HEADER] = 'test'
        # ... Even if the user is good, the API key makes us
        # distrust this request.
        self.request.user = self.dataset.owner
        response = self.view(self.request, **self.uri_args)
        assert_equal(response.status_code, 403)
