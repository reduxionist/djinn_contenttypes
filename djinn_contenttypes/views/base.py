from django.views.generic.detail import DetailView as BaseDetailView
from django.views.generic.edit import UpdateView as BaseUpdateView
from django.views.generic.edit import DeleteView as BaseDeleteView
from django.views.generic.edit import CreateView as BaseCreateView
from django.http import HttpResponseRedirect, HttpResponse, \
    HttpResponseForbidden
from django.db import models
from django.db.models import get_model
from django.core.urlresolvers import reverse
from django.contrib import messages
from django.utils.translation import ugettext_lazy as _
from djinn_core.utils import implements
from djinn_contenttypes.registry import CTRegistry
from djinn_contenttypes.utils import get_object_by_ctype_id, has_permission
from djinn_contenttypes.models.base import BaseContent
from pgauth.models import UserGroup
from django.core.exceptions import ImproperlyConfigured


class TemplateResolverMixin(object):

    @property
    def app_label(self):
        return self.model.__module__.split(".")[0]

    @property
    def ct_name(self):
        return self.model.__name__.lower()

    @property
    def ct_label(self):
        return _(self.model.__name__)

    def get_template_names(self):

        if self.template_name:
            return [self.template_name]

        if self.request.GET.get("modal", False) or self.request.is_ajax():
            modal = "_modal"
        else:
            modal = ""

        return ["%s/%s_%s%s.html" % (self.app_label, self.ct_name, self.mode,
                modal),
                "djinn_contenttypes/base_%s%s.html" % (self.mode, modal)
                ]

    @property
    def delete_url(self):

        return reverse("%s_delete_%s" % (self.app_label, self.ct_name),
                       kwargs={'pk': self.object.id})

    @property
    def add_url(self):

        return reverse("%s_add_%s" % (self.app_label, self.ct_name),
                       kwargs=self.kwargs)

    @property
    def edit_url(self):

        return reverse("%s_edit_%s" % (self.app_label, self.ct_name),
                       kwargs={'pk': self.object.id})

    @property
    def view_url(self):

        kwargs = {"pk": self.object.id}

        if hasattr(self.object, "slug"):
            kwargs.update({"slug": self.object.slug})

        return reverse('%s_view_%s' % (self.app_label, self.ct_name),
                       kwargs=kwargs)


class MimeTypeMixin(object):

    mimetype = "text/html"

    def render_to_response(self, context, **response_kwargs):

        """ Override so as to add mimetype """

        response_kwargs['mimetype'] = self.mimetype

        return super(MimeTypeMixin, self).render_to_response(
            context, **response_kwargs)


class CTMixin(object):

    """ Detailview that applies to any content, determined by the url parts """

    def get_object(self, queryset=None):

        """ Retrieve context from URL parts app, ctype and id."""

        return get_object_by_ctype_id(
            self.kwargs['ctype'],
            self.kwargs.get('id', self.kwargs.get('pk', None)))


class SwappableMixin(object):

    """ Allow for swapped models. This is an undocumented feature of
    the meta class for now, that enables user defined overrides for
    models (i.e. contrib.auth.User)"""

    @property
    def real_model(self):

        if not self.model._meta.swapped:
            return self.model
        else:
            module, model = self.model._meta.swapped.split(".")
            return get_model(module, model)

    def get_queryset(self):

        """ Override default get_queryset to allow for swappable models """

        if self.queryset is None:
            if self.model:
                return self.real_model._default_manager.all()
            else:
                raise ImproperlyConfigured(
                    "%(cls)s is missing a queryset. Define "
                    "%(cls)s.model, %(cls)s.queryset, or override "
                    "%(cls)s.get_queryset()." % {
                        'cls': self.__class__.__name__
                    })
        return self.queryset._clone()


class DetailView(TemplateResolverMixin, SwappableMixin, BaseDetailView):

    """ Detail view for simple content, not related, etc. All intranet
    detail views should extend this view.
    """

    mode = "detail"

    def get_template_names(self):

        """ If the request is Ajax, and no one asked for a modal view,
        assume that we need to return a record like view"""

        if self.template_name:
            return [self.template_name]

        templates = super(DetailView, self).get_template_names()

        if self.request.is_ajax() and \
                not self.request.REQUEST.get("modal", False):
            templates = ["%s/snippets/%s.html" %
                         (self.app_label, self.ct_name)] \
                + templates

        return templates

    def get(self, request, *args, **kwargs):

        """ We need our own implementation of GET, to be able to do permission
        checks on the object """

        self.object = self.get_object()

        perm = CTRegistry.get(self.ct_name).get("view_permission",
                                                'contenttypes.view')

        if not has_permission(perm, self.request.user, self.object):
            return HttpResponseForbidden()

        context = self.get_context_data(object=self.object)
        mimetype = "text/html"

        if self.request.is_ajax():
            mimetype = "text/plain"

        return self.render_to_response(context, mimetype=mimetype)


class CTDetailView(CTMixin, DetailView):

    """ Detailview that applies to any content, determined by the url parts """


class CreateView(TemplateResolverMixin, SwappableMixin, BaseCreateView):

    mode = "add"
    fk_fields = []

    def get_initial(self):

        initial = {}

        for fld in self.request.GET.keys():
            initial[fld] = self.request.GET[fld]

        for fld in self.fk_fields:
            initial[fld] = self.kwargs[fld]

        return initial

    def get_success_url(self):

        return self.view_url

    def get_object(self, queryset=None):

        if not getattr(self.real_model, "create_tmp_object", False):
            return None
        else:
            if self.request.REQUEST.get("is_tmp"):
                obj = self.real_model.objects.get(
                    id=self.request.REQUEST.get("is_tmp"))
            else:
                obj = self.real_model.objects.create(
                    creator=self.request.user,
                    changed_by=self.request.user
                    )

                # Set any data that is available, i.e. through initial data
                #
                if self.get_initial():
                    form_class = self.get_form_class()
                    form = form_class(data=self.get_initial(),
                                      **self.get_form_kwargs())
                    form.cleaned_data = {}
                    
                    for field in self.get_initial().keys():
                        value = form.fields[field].clean(form.data[field])
                        setattr(obj, field, value)

            obj.save()

            return obj

    def get(self, request, *args, **kwargs):

        """ Override get so as to be able to check permissions """

        # TODO: this should be the more specific permission
        perm = CTRegistry.get(self.ct_name).get("add_permission",
                                                'contenttypes.add_contenttype')

        # TODO: check if this still exists...
        ugid = kwargs.get('parentusergroup', None)

        if ugid:
            context = UserGroup.objects.get(id=int(ugid)).profile
        else:
            context = None

        if not self.request.user.has_perm(perm, obj=context):
            return HttpResponseForbidden()

        self.object = self.get_object()

        form_class = self.get_form_class()
        form = self.get_form(form_class)

        return self.render_to_response(self.get_context_data(form=form))

    def post(self, request, *args, **kwargs):

        perm = CTRegistry.get(self.ct_name).get("add_permission",
                                                'contenttypes.add_contenttype')

        pugid = kwargs.get('parentusergroup', None)

        if pugid:
            theobj = UserGroup.objects.get(id=int(pugid)).profile
        else:
            theobj = None
        if not self.request.user.has_perm(perm, obj=theobj):
            return HttpResponseForbidden()

        self.object = self.get_object()

        if self.request.POST.get('action', None) == "cancel":

            # There may be a temporary object...
            try:
                if getattr(self.object, "is_tmp", False):
                    self.object.delete()
            except:
                pass

            return HttpResponseRedirect(
                request.user.profile.get_absolute_url())
        else:
            form_class = self.get_form_class()
            form = self.get_form(form_class)

            if form.is_valid():
                return self.form_valid(form)
            else:
                return self.form_invalid(form)

    def form_valid(self, form):

        self.object = form.save(commit=False)

        # Assume, but not overly, that this is BaseContent...
        #
        try:
            self.object.creator = self.request.user
            self.object.changed_by = self.request.user
            self.object.is_tmp = False
        except:
            pass

        self.object.save()

        if implements(self.object, BaseContent):
            self.object.set_owner(self.request.user)

        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form),
                                       status=202)


class UpdateView(TemplateResolverMixin, SwappableMixin, BaseUpdateView):

    mode = "edit"

    def get_success_url(self):

        return self.view_url

    @property
    def partial(self):

        """ Allow partial update """

        return self.request.REQUEST.get('partial', False)

    def get_form_kwargs(self):

        kwargs = super(UpdateView, self).get_form_kwargs()

        kwargs['partial'] = self.partial

        return kwargs

    def get_initial(self):

        initial = {}

        for fld in self.request.GET.keys():
            initial[fld] = self.request.GET[fld]

        return initial

    def get(self, request, *args, **kwargs):

        """ Check permissions for editing """

        self.object = self.get_object()

        perm = CTRegistry.get(self.ct_name).get(
            "edit_permission",
            'contenttypes.change_contenttype')

        if not has_permission(perm, self.request.user, self.object):
            return HttpResponseForbidden()

        return super(UpdateView, self).post(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):

        """ Check whether the user wants to cancel the whole
        operation. If so, we need to check whether is was an edit, or
        initial object. If the latter is the case, delete the 'tmp'
        object."""

        self.object = self.get_object()

        perm = CTRegistry.get(self.ct_name).get(
            "edit_permission",
            'contenttypes.change_contenttype')

        if not has_permission(perm, self.request.user, self.object):
            return HttpResponseForbidden()

        if self.request.POST.get('action', None) == "cancel":

            if getattr(self.object, "is_tmp", False):
                self.object.delete()
                return HttpResponseRedirect(
                    request.user.profile.get_absolute_url())

            return HttpResponseRedirect(self.object.get_absolute_url())
        else:
            return super(UpdateView, self).post(request, *args, **kwargs)

    def form_valid(self, form):

        if hasattr(form, "update") and self.partial:
            self.object = form.update()
        else:
            self.object = form.save()

        if implements(self.object, BaseContent):
            self.object.changed_by = self.request.user

        try:
            self.object.is_tmp = False
        except:
            pass

        self.object.save()

        # Translators: edit form status message
        messages.success(self.request, _("Saved changes"))
        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form),
                                       status=202)


class DeleteView(TemplateResolverMixin, SwappableMixin, BaseDeleteView):

    mode = "delete"

    def delete(self, request, *args, **kwargs):

        self.object = self.get_object()

        perm = CTRegistry.get(self.ct_name).get(
            "delete_permission",
            'contenttypes.delete_contenttype')

        if not has_permission(perm, self.request.user, self.object):
            return HttpResponseForbidden()

        try:
            # enable signal handlers to access last change info
            #
            if implements(self.object, BaseContent):
                self.object.changed_by = self.request.user

            self.object.delete()
        except Exception:
            return HttpResponseRedirect(self.view_url)

        if self.request.is_ajax():
            return HttpResponse("Bye bye", content_type='text/plain')
        else:
            return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):

        """ Return the URL to which the edit/create action should
        return upon success"""

        return self.request.user.profile.get_absolute_url()

    def get(self, request, *args, **kwargs):

        """ Make sure that the confirm delete is sent as text/plain """

        self.object = self.get_object()
        context = self.get_context_data(object=self.object, **kwargs)

        return self.render_to_response(context, mimetype="text/plain")
