# -*- coding: utf-8 -*-


from odoo import api, models, fields

class SaleOrder(models.Model):
    _inherit = 'sale.order'


    email_content = fields.Char()
