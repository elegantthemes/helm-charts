{{ define "screenshot.container.worker" }}
        - name: worker-{{ .index }}
          env:
            - name: NODE_NAME
              valueFrom:
                fieldRef:
                  fieldPath: spec.nodeName
            - name: CLOUD_SCREENSHOT_PATH
              value: '{{ .Values.INSTALL_PATH }}'
            - name: VIRTUAL_HOST
              value: '{{ .Values.VIRTUAL_HOST }}'
            - name: CLOUD_SCREENSHOT_REPO_URL
              value: '{{ .Values.CLOUD_SCREENSHOT_REPO_URL }}'
            - name: IMAGE_VERSION
              value: '{{ .Values.CLOUD_SCREENSHOT_VERSION }}'
            - name: CLOUD_SCREENSHOT_WORKER
              value: '1'
          image: '{{ .Values.CLOUD_SCREENSHOT_IMAGE }}'
          resources:
            requests:
              cpu: 100m
              memory: 100Mi
            limits:
              cpu: '2'
              memory: 1G
          volumeMounts:
            - name: wordpress
              mountPath: /srv
            - name: config
              mountPath: /config
              readOnly: true
{{ end }}
