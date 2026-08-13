"""Edges to systems JAL-SAKSHI does not own: n8n, Telegram, and the console's
realtime stream.

Everything here is failure-tolerant by construction. A webhook that is down, a
secret that is wrong, a console that disconnected mid-incident — none of those
may stop a work order from being assigned, escalated, verified or closed. The
water system is the product; the messaging is how it tells people about itself.
"""
