from datetime import datetime, timedelta
from django.test.testcases import TestCase
from django.db import models
from django.contrib.auth import get_user_model


class PublishableTest(TestCase):

    def setUp(self):

        news_model = models.get_model("djinn_news", "News")
        user_model = get_user_model()

        self.user = user_model.objects.create(username="bobdobalina")
        self.content = news_model.objects.create(
            changed_by=self.user,
            title="test news",
            creator=self.user)

    def test_is_public(self):

        self.assertTrue(self.content.is_public)
        
        self.content.is_tmp = True

        self.assertFalse(self.content.is_public)

    def test_is_published(self):

        tomorrow = datetime.now() + timedelta(days=1)
        yesterday = datetime.now() - timedelta(days=1)

        self.assertTrue(self.content.is_published)

        self.content.publish_from = tomorrow

        self.assertFalse(self.content.is_published)

        self.content.publish_from = yesterday
        
        self.assertTrue(self.content.is_published)

        self.content.publish_to = tomorrow

        self.assertTrue(self.content.is_published)

        self.content.publish_to = yesterday

        self.assertFalse(self.content.is_published)