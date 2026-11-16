{{ fullname | escape | underline }}

.. automodule:: {{ fullname }}
   :members:
   :undoc-members:
   :show-inheritance:

{% block modules %}
{% if modules %}
.. rubric:: Modules

.. autosummary::
   :toctree:
   :recursive:
{% for item in modules %}
{%- if (fullname ~ "." ~ item) not in skip_modules %}
   {{ item }}
{%- endif %}
{%- endfor %}
{% endif %}
{% endblock %}
