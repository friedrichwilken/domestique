"""Web console: the claims report as HTML and JSON, served beside the database.

``queries`` builds one ``ReportData`` from the database or from a replay
result, ``charts`` turns it into table rows and inline SVG, ``pages`` renders
the Jinja2 templates and ``app`` serves them. No language-model dependency.
"""
