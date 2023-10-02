Mail
#################

Robusta can report issues and events in your Kubernetes cluster by sending
emails.

To configure the mail sink you need access to an SMTP server.

Connecting the mail sink
------------------------------------------------

.. admonition:: Add this to your generated_values.yaml

    .. code-block:: yaml

        sinksConfig:
        - mail_sink:
            name: mail_sink
            mailto: mailtos://user:password@server&from=a@x&to=b@y,c@z

Then do a :ref:`Helm Upgrade <Simple Upgrade>`.

TODO: document the mailto format (reference to Apprise docs)
