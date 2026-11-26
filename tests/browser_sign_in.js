// Used only with browser_harness.py. Tokens and keys are generated for this local run.
(async () => {
  const fakeClerk = {
    session: null,
    mountSignIn: element => { element.textContent = 'Test sign-in'; },
    unmountSignIn: element => { element.textContent = ''; },
    mountUserButton: element => { element.innerHTML = '<span class="avatar">PT</span>'; },
    unmountUserButton: element => { element.textContent = ''; },
    mountOrganizationSwitcher: element => { element.textContent = 'Personal workspace'; },
    unmountOrganizationSwitcher: element => { element.textContent = ''; },
  };
  clerk = fakeClerk;
  window.__browserTestSelectAccount = (name, workspace = 'personal') => {
    fakeClerk.session = name ? {
      id: 'sess_' + name, status: 'active',
      getToken: async () => (await fetch('/__browser_test/token/' + name + '?workspace=' + workspace)).text(),
    } : null;
    fakeClerk.organization = name && workspace !== 'personal' ? {id: workspace} : null;
    setAuthState({session: fakeClerk.session, organization: fakeClerk.organization});
    if (name) document.getElementById('organization-switcher').textContent = workspace === 'personal' ? 'Personal workspace' : 'Team workspace';
  };
  activeIdentityKey = undefined;
  window.__browserTestSelectAccount('alice');
  return 'Test account selected';
})()
