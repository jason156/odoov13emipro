# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import werkzeug
from odoo import http
from odoo.addons.web.controllers.main import Home
from odoo.addons.sale.controllers.portal import CustomerPortal
from odoo.addons.auth_signup.controllers.main import AuthSignupHome
from odoo.http import request
from odoo.tools.translate import _
from odoo.addons.auth_signup.models.res_users import SignupError
from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo.exceptions import UserError
from werkzeug.exceptions import NotFound

_logger = logging.getLogger(__name__)


class CustomerPortal(CustomerPortal):
    @http.route()
    def payment_transaction_token(self, acquirer_id, order_id, save_token=False, access_token=None, **kwargs):
        result = super(CustomerPortal, self).payment_transaction_token(acquirer_id, order_id, save_token=False, access_token=None, **kwargs)
        user_id = request.session.uid
        partnerId = request.env['res.users'].browse(user_id).partner_id.id
        companyPartner = request.env['res.users'].browse(user_id).partner_id.parent_id.id
        request.env['sale.order'].browse(order_id).sudo().message_subscribe(partner_ids=[partnerId,companyPartner])
        return result

    @http.route(['/my/orders/<int:order_id>'], type='http', auth="public", website=True)
    def portal_order_page(self, order_id, report_type=None, access_token=None, message=False, download=False, **kw):
        res = super(CustomerPortal, self).portal_order_page(order_id=order_id,report_type=report_type,access_token=access_token,message=message,download=download,**kw)
        if res.qcontext.get('acquirers',False):
            default_wire_transfer = request.env.ref('payment.payment_acquirer_transfer')
            acquirers = res.qcontext.get('acquirers')
            if default_wire_transfer and acquirers:
                if default_wire_transfer in acquirers:
                    current_login_user = request.env['res.users'].sudo().search([('id','=',request.session.uid)])
                    if current_login_user:
                        if current_login_user.partner_id.company_type == 'company':
                            if not current_login_user.partner_id.property_payment_term_id:
                                acquirers = acquirers.filtered(lambda acq: not acq == default_wire_transfer)
                                res.qcontext.update({'acquirers': acquirers})
                        else:
                            if not current_login_user.partner_id.parent_id.property_payment_term_id or not current_login_user.partner_id.parent_id:
                                acquirers = acquirers.filtered(lambda acq: not acq == default_wire_transfer)
                                res.qcontext.update({'acquirers': acquirers})
        return res
        
        
class EptUserAccess(http.Controller):

    @http.route(['/create_order_quote'], type='http', auth="public", website=True, csrf=False)
    def create_quote(self):
        so = request.website.sale_get_order()
        email_act = so.action_quotation_send()
        email_ctx = email_act.get('context', {})
        user_id = request.session.uid
        companyPartner = request.env['res.users'].browse(user_id).partner_id.parent_id.id
        so.sudo().message_subscribe(partner_ids=[companyPartner])
        so.with_context(**email_ctx).message_post_with_template(email_ctx.get('default_template_id'))
        template = request.env['mail.template'].browse(email_ctx.get('default_template_id'))
        template.sudo().send_mail(so.id, force_send=True)
        if request.session.get('sale_order_id'):
            request.session['sale_order_id'] = None
        return request.render("user_access.quote_confirmation")

    @http.route(['/send/confirmation/mail'], type='http', auth="public", website=True, csrf=False)
    def send_confirmation_mail(self):
        return request.render("user_access.signup_confirmation")

    @http.route(['/send_quote'], type='json', auth="public", website=True,csrf=False)
    def send_quote_with_mail(self, **kwargs):
        email = kwargs.get('email', False)
        content = kwargs.get('content', False)
        userId = request.env['res.users'].sudo().search([('login', '=', email)])
        if userId:
            sale_order = request.website.sale_get_order()
            access_token = sale_order.get_portal_url()
            sale_order.email_content = content
            if userId.user_role in ['l2']:
                template = request.env.ref('user_access.mail_template_send_quote_template',
                                           raise_if_not_found=False)
                template.sudo().send_mail(sale_order.id, force_send=True,email_values={'recipient_ids': [(4, userId.partner_id.id)]})
                return True
        return False

    @http.route(['/send_portal_quote'], type='json', auth="public", website=True, csrf=False)
    def send_quote_with_mail(self, **kwargs):
        email = kwargs.get('email', False)
        content = kwargs.get('content', False)
        order_id = kwargs.get('order_id', False)
        userId = request.env['res.users'].sudo().search([('login', '=', email)])
        if userId and order_id:
            sale_order = request.env['sale.order'].sudo().browse(int(order_id))
            sale_order.email_content = content
            if userId.user_role in ['l2']:
                template = request.env.ref('user_access.mail_template_send_quote_template',
                                           raise_if_not_found=False)
                template.sudo().send_mail(sale_order.id, force_send=True,
                                          email_values={'recipient_ids': [(4, userId.partner_id.id)]})
                return True
        return False



class Home(Home):

    @http.route()
    def web_login(self, redirect=None, **kw):
        if request.params and not request.params['redirect']:
            email_domain = request.website.email_domain
            if request.params['login'] and email_domain:
                user = request.env['res.users'].sudo().search([('login', '=', request.params['login'])])
                if user.share:
                    email_has = email_domain.split("@")
                    username = request.params['login']
                    allow = username.find(email_has[1])
                    if (allow == -1):
                        request.params['error'] = _("Email domain must be end with ") + str('"' + email_has[1] + '"')
                        return request.render('web.login', request.params)

                    if user and not user.is_validate:
                        request.params['error'] = _("User is not validate please check your email..")
                        return request.render('web.login', request.params)
        return super(Home, self).web_login(redirect, **kw)


class WebsiteSale(WebsiteSale):
    @http.route()
    def cart(self, access_token=None, revive='', **post):
        if request.session.login:
            return super(WebsiteSale, self).cart(access_token=None, revive='', **post)
        else:
            raise NotFound()

    def _get_shop_payment_values(self, order, **kwargs):
        res = super(WebsiteSale, self)._get_shop_payment_values(order=order, **kwargs)
        acquirers = res.get('acquirers')
        default_wire_transfer = request.env.ref('payment.payment_acquirer_transfer')
        if acquirers and default_wire_transfer:
            if default_wire_transfer in acquirers:
                current_login_user = request.env['res.users'].sudo().search([('id', '=', request.session.uid)])
                if current_login_user:
                    if current_login_user.partner_id.company_type == 'company':
                        if not current_login_user.partner_id.property_payment_term_id:
                            acquirers.pop(acquirers.index(default_wire_transfer))
                            res.update({'acquirers': acquirers})
                    else:
                        if not current_login_user.partner_id.parent_id.property_payment_term_id or not current_login_user.partner_id.parent_id:
                            acquirers.pop(acquirers.index(default_wire_transfer))
                            res.update({'acquirers': acquirers})
        return res

class AuthSignupHome(AuthSignupHome):

    @http.route()
    def web_auth_signup(self, *args, **kw):
        qcontext = AuthSignupHome.get_auth_signup_qcontext(self)

        email_domain = request.website.email_domain
        if qcontext and qcontext.get('login') and email_domain:
            username = qcontext.get('login')
            email_has = email_domain.split("@")
            allow = username.find(email_has[1])
            if (allow == -1):
                qcontext['error'] = _("Email domain must be end with ") + str('"' + email_has[1] + '"')
                return request.render('auth_signup.signup', qcontext)

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if 'error' not in qcontext and request.httprequest.method == 'POST':

            try:
                self.do_signup(qcontext)
                # Send an account creation confirmation email
                if qcontext.get('token'):
                    user_sudo = request.env['res.users'].sudo().search([('login', '=', qcontext.get('login'))])
                    template = request.env.ref('auth_signup.mail_template_user_signup_account_created',
                                               raise_if_not_found=False)
                    if user_sudo and template:
                        template.sudo().with_context(
                            lang=user_sudo.lang,
                            auth_login=werkzeug.url_encode({'auth_login': user_sudo.email}),
                        ).send_mail(user_sudo.id, force_send=True)
                if qcontext.get('token'):
                    return self.web_login(*args, **kw)
                else:
                    return request.render("user_access.signup_confirmation")
            except UserError as e:
                qcontext['error'] = e.name or e.value
            except (SignupError, AssertionError) as e:
                if request.env["res.users"].sudo().search([("login", "=", qcontext.get("login"))]):
                    qcontext["error"] = _("Another user is already registered using this email address.")
                else:
                    _logger.error("%s", e)
                    qcontext['error'] = _("Could not create a new account.")

        response = request.render('auth_signup.signup', qcontext)
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    def do_signup(self, qcontext):
        """ Shared helper that creates a res.partner out of a token """
        values = {key: qcontext.get(key) for key in ('login', 'name', 'password')}
        if not values:
            raise UserError(_("The form was not properly filled in."))
        if values.get('password') != qcontext.get('confirm_password'):
            raise UserError(_("Passwords do not match; please retype them."))
        supported_lang_codes = [code for code, _ in request.env['res.lang'].get_installed()]
        lang = request.context.get('lang', '').split('_')[0]
        if lang in supported_lang_codes:
            values['lang'] = lang
        self._signup_with_values(qcontext.get('token'), values)
        request.env.cr.commit()

    def _signup_with_values(self, token, values):
        db, login, password = request.env['res.users'].sudo().signup(values, token)
        request.env.cr.commit()  # as authenticate will use its own cursor we need to commit the current transaction
        user_sudo = request.env['res.users'].sudo().search([('login', '=', login)])
        if not token:
            template = request.env.ref('user_access.mail_template_user_signup_confirmation',
                                       raise_if_not_found=False)
            template.sudo().send_mail(user_sudo.id, force_send=True)

    @http.route('/web/signup/confirmation', type='http', auth='public', website=True)
    def signup_confirmation(self, access_token=False):
        if access_token:
            user_id = request.env['res.users'].sudo().search([('access_token', '=', access_token)])
            user_id.sudo().write({
                'is_validate': True,
                'user_role': 'l1',
            })
            if user_id.is_validate == True:
                request.env.cr.commit()
                if user_id is not False:
                    request.params['login_success'] = True
                    if user_id.redirect_url:
                        return request.redirect(user_id.redirect_url)
                    else:
                        return request.render("user_access.user_valid")
            else:
                return request.render("user_access.signup_not_valid_user")
