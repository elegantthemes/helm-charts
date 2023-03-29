{{ define "screenshot.container.worker" }}
        - name: worker-{{ .index }}
          env:
            - name: NODE_NAME
              valueFrom:
                fieldRef:
                  fieldPath: spec.nodeName
            - name: CLOUD_SCREENSHOT_PATH
              value: {{ .Values.INSTALL_PATH | squote }}
            - name: VIRTUAL_HOST
              value: {{ .Values.VIRTUAL_HOST | squote }}
            - name: CLOUD_SCREENSHOT_REPO_URL
              value: {{ .Values.CLOUD_SCREENSHOT_REPO_URL | squote }}
            - name: IMAGE_VERSION
              value: {{ .Values.CLOUD_SCREENSHOT_VERSION | squote }}
            - name: CLOUD_SCREENSHOT_WORKER
              value: '1'
            - name: PHP_OPCACHE_FILE_CACHE
              value: {{ ternary "/var/cache/php" "" (eq "production" .Values.WP_ENV) | squote }}
            - name: PHP_OPCACHE_VALIDATE_TIMESTAMPS
              value: {{ ternary "false" "true" (eq "production" .Values.WP_ENV) | squote }}
          image: {{ .Values.CLOUD_SCREENSHOT_IMAGE | squote }}
          resources:
            requests:
              cpu: 100m
              memory: 100Mi
            limits:
              cpu: '2'
              memory: 2G
          volumeMounts:
            - name: wordpress
              mountPath: /srv
            - name: config
              mountPath: /config
              readOnly: true
{{ end }}
