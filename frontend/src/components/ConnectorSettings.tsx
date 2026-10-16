import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle, Clipboard, Edit2, Loader2, Plug, RefreshCw, Save, Shield, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api, type Connector } from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';
import { Button } from './Button';
import { Card, CardContent, CardHeader } from './Card';
import { ConfirmModal } from './ConfirmModal';

function formatDate(value: string | null, language: string): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(language, { dateStyle: 'medium', timeStyle: 'short' });
}

export function ConnectorSettings() {
  const { t, i18n } = useTranslation();
  const { authEnabled, hasPermission } = useAuth();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const canRead = !authEnabled || hasPermission('connectors:read');
  const canCreate = !authEnabled || hasPermission('connectors:create');
  const canUpdate = !authEnabled || hasPermission('connectors:update');
  const canRevoke = !authEnabled || hasPermission('connectors:revoke');

  const [enrollmentName, setEnrollmentName] = useState('');
  const [enrollment, setEnrollment] = useState<{ code: string; expiresAt: string } | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState('');
  const [revokeTarget, setRevokeTarget] = useState<Connector | null>(null);

  const connectorsQuery = useQuery({
    queryKey: ['connectors'],
    queryFn: api.listConnectors,
    enabled: canRead,
    refetchInterval: 15000,
  });

  const createEnrollmentMutation = useMutation({
    mutationFn: () => api.createConnectorEnrollment({
      name: enrollmentName.trim() || undefined,
      ttl_seconds: 600,
    }),
    onSuccess: (data) => {
      setEnrollment({ code: data.enrollment_code, expiresAt: data.expires_at });
      setEnrollmentName('');
      showToast(t('settings.connectors.enrollmentCreated'), 'success');
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => api.updateConnector(id, { name }),
    onSuccess: () => {
      setEditingId(null);
      queryClient.invalidateQueries({ queryKey: ['connectors'] });
      showToast(t('settings.connectors.renamed'), 'success');
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => api.revokeConnector(id),
    onSuccess: () => {
      setRevokeTarget(null);
      queryClient.invalidateQueries({ queryKey: ['connectors'] });
      showToast(t('settings.connectors.revoked'), 'success');
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const copyEnrollmentCode = async () => {
    if (!enrollment) return;
    try {
      await navigator.clipboard.writeText(enrollment.code);
      showToast(t('common.copied'), 'success');
    } catch {
      showToast(t('settings.connectors.copyFailed'), 'error');
    }
  };

  if (authEnabled && !canRead) {
    return (
      <Card id="card-connectors">
        <CardContent className="py-8 text-center text-bambu-gray">
          <Shield className="w-8 h-8 mx-auto mb-2 opacity-60" />
          {t('settings.connectors.noReadPermission')}
        </CardContent>
      </Card>
    );
  }

  return (
    <div id="card-connectors" className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                <Plug className="w-5 h-5 text-bambu-green" />
                {t('settings.connectors.title')}
              </h2>
              <p className="text-sm text-bambu-gray mt-1">{t('settings.connectors.description')}</p>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => connectorsQuery.refetch()}
              disabled={connectorsQuery.isFetching}
              aria-label={t('common.refresh')}
            >
              <RefreshCw className={`w-4 h-4 ${connectorsQuery.isFetching ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </CardHeader>
        {canCreate && (
          <CardContent className="border-t border-bambu-dark-tertiary space-y-3">
            <div>
              <h3 className="text-sm font-semibold text-white">{t('settings.connectors.createTitle')}</h3>
              <p className="text-xs text-bambu-gray mt-1">{t('settings.connectors.createDescription')}</p>
            </div>
            <div className="flex flex-col sm:flex-row gap-2">
              <input
                value={enrollmentName}
                onChange={(event) => setEnrollmentName(event.target.value)}
                maxLength={100}
                placeholder={t('settings.connectors.namePlaceholder')}
                className="flex-1 px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white text-sm focus:border-bambu-green focus:outline-none"
              />
              <Button
                onClick={() => createEnrollmentMutation.mutate()}
                disabled={createEnrollmentMutation.isPending}
              >
                {createEnrollmentMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plug className="w-4 h-4" />}
                {t('settings.connectors.createCode')}
              </Button>
            </div>
            {enrollment && (
              <div className="rounded-lg border border-yellow-500/40 bg-yellow-500/10 p-3 space-y-2">
                <p className="text-sm font-semibold text-yellow-200">{t('settings.connectors.codeShownOnce')}</p>
                <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
                  <code className="flex-1 min-w-0 break-all rounded bg-bambu-dark px-3 py-2 text-sm text-white">{enrollment.code}</code>
                  <Button variant="secondary" size="sm" onClick={copyEnrollmentCode}>
                    <Clipboard className="w-4 h-4" />
                    {t('common.copy')}
                  </Button>
                </div>
                <p className="text-xs text-yellow-100/80">
                  {t('settings.connectors.expiresAt', { date: formatDate(enrollment.expiresAt, i18n.language) })}
                </p>
              </div>
            )}
          </CardContent>
        )}
      </Card>

      <Card>
        <CardHeader>
          <h2 className="text-base font-semibold text-white">{t('settings.connectors.listTitle')}</h2>
        </CardHeader>
        <CardContent>
          {connectorsQuery.isLoading && (
            <div className="flex justify-center py-8"><Loader2 className="w-6 h-6 text-bambu-green animate-spin" /></div>
          )}
          {connectorsQuery.isError && (
            <div className="py-6 text-center text-red-300 text-sm">{t('settings.connectors.loadFailed')}</div>
          )}
          {!connectorsQuery.isLoading && !connectorsQuery.isError && connectorsQuery.data?.length === 0 && (
            <div className="py-8 text-center text-bambu-gray text-sm">{t('settings.connectors.empty')}</div>
          )}
          <div className="space-y-2">
            {(connectorsQuery.data ?? []).map((connector) => {
              const isEditing = editingId === connector.public_id;
              const isRevoked = connector.status === 'revoked' || !!connector.revoked_at;
              return (
                <div key={connector.public_id} className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark/40 p-3">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        {isEditing ? (
                          <input
                            autoFocus
                            value={editingName}
                            onChange={(event) => setEditingName(event.target.value)}
                            maxLength={100}
                            className="px-2 py-1 bg-bambu-dark border border-bambu-green rounded text-white text-sm focus:outline-none"
                          />
                        ) : (
                          <span className="font-medium text-white truncate">{connector.name}</span>
                        )}
                        <span className={`inline-flex items-center gap-1 text-xs ${isRevoked ? 'text-red-300' : connector.status === 'online' ? 'text-green-300' : 'text-bambu-gray'}`}>
                          {connector.status === 'online' && !isRevoked ? <CheckCircle className="w-3.5 h-3.5" /> : <XCircle className="w-3.5 h-3.5" />}
                          {t(`settings.connectors.status.${isRevoked ? 'revoked' : connector.status}`, connector.status)}
                        </span>
                      </div>
                      <div className="mt-1 grid grid-cols-1 sm:grid-cols-3 gap-x-4 gap-y-1 text-xs text-bambu-gray">
                        <span>{t('settings.connectors.version')}: {connector.version || '—'}</span>
                        <span>{t('settings.connectors.platform')}: {connector.platform || '—'}</span>
                        <span>{t('settings.connectors.lastSeen')}: {formatDate(connector.last_seen_at, i18n.language)}</span>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {canUpdate && !isRevoked && (isEditing ? (
                        <>
                          <Button size="sm" onClick={() => updateMutation.mutate({ id: connector.public_id, name: editingName.trim() })} disabled={!editingName.trim() || updateMutation.isPending}>
                            <Save className="w-4 h-4" /> {t('common.save')}
                          </Button>
                          <Button size="sm" variant="secondary" onClick={() => setEditingId(null)}>{t('common.cancel')}</Button>
                        </>
                      ) : (
                        <Button size="sm" variant="secondary" onClick={() => { setEditingId(connector.public_id); setEditingName(connector.name); }}>
                          <Edit2 className="w-4 h-4" /> {t('common.rename')}
                        </Button>
                      ))}
                      {canRevoke && !isRevoked && (
                        <Button size="sm" variant="danger" onClick={() => setRevokeTarget(connector)}>
                          {t('settings.connectors.revoke')}
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {revokeTarget && (
        <ConfirmModal
          title={t('settings.connectors.revokeTitle')}
          message={t('settings.connectors.revokeMessage', { name: revokeTarget.name })}
          confirmText={t('settings.connectors.revoke')}
          variant="danger"
          isLoading={revokeMutation.isPending}
          onCancel={() => setRevokeTarget(null)}
          onConfirm={() => revokeMutation.mutate(revokeTarget.public_id)}
        />
      )}
    </div>
  );
}
