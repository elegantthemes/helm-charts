{{ define "hub.container.worker" }}
        - name: worker-{{ .index }}
          env:
            - name: NODE_NAME
              valueFrom:
                fieldRef:
                  fieldPath: spec.nodeName
            - name: HUB_SERVER_PATH
              value: {{ .Values.HUB_SERVER_PATH | squote }}
            - name: VIRTUAL_HOST
              value: {{ .Values.VIRTUAL_HOST | squote }}
            - name: HUB_SERVER_REPO_URL
              value: {{ .Values.HUB_SERVER_REPO_URL | squote }}
            - name: IMAGE_VERSION
              value: {{ .Values.HUB_SERVER_VERSION | squote }}
            - name: HUB_SERVER_WORKER
              value: '1'
            - name: PHP_OPCACHE_FILE_CACHE
              value: {{ ternary "/var/cache/php" "" (eq "production" .Values.HUB_SERVER_ENV) | squote }}
            - name: PHP_OPCACHE_VALIDATE_TIMESTAMPS
              value: {{ ternary "false" "true" (eq "production" .Values.HUB_SERVER_ENV) | squote }}
          image: {{ .Values.HUB_SERVER_IMAGE | squote }}
          resources:
            requests:
              cpu: 100m
              memory: 100Mi
            limits:
              cpu: '4'
              memory: 4G
          volumeMounts:
            - name: wordpress
              mountPath: /srv
            - name: config
              mountPath: /config
              readOnly: true
{{ end }}
