/**
 * Agent Playground JavaScript
 *
 * Handles the interactive agent testing console UI.
 */

(function () {
  'use strict';

  // ============================================================================
  // State
  // ============================================================================

  const state = {
    currentAgent: null,
    sessionId: null,
    agents: [],
    skills: [],
    messages: [],
    totalTokens: 0,
    totalCost: 0,
    config: {
      model: 'claude-sonnet-4-5-20250929',
      temperature: 0.3,
      maxTokens: 4096,
      enabledSkills: [],
      systemPromptOverride: null,
    },
  };

  // ============================================================================
  // API Functions
  // ============================================================================

  async function fetchAgents() {
    try {
      const response = await fetch('/playground/agents');
      if (!response.ok) throw new Error('Failed to fetch agents');
      return await response.json();
    } catch (error) {
      console.error('Error fetching agents:', error);
      return [];
    }
  }

  async function fetchSkills() {
    try {
      const response = await fetch('/playground/skills');
      if (!response.ok) throw new Error('Failed to fetch skills');
      return await response.json();
    } catch (error) {
      console.error('Error fetching skills:', error);
      return [];
    }
  }

  async function sendMessage(agentId, message, config) {
    const body = {
      message,
      session_id: state.sessionId,
      stream: true,
      config_override: config,
    };

    const response = await fetch(`/playground/agents/${agentId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to send message');
    }

    return response;
  }

  async function executeSkill(skillName, actionName, params) {
    const response = await fetch(
      `/playground/skills/${skillName}/actions/${actionName}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      }
    );

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to execute skill');
    }

    return await response.json();
  }

  // ============================================================================
  // UI Rendering
  // ============================================================================

  function renderAgentCards(agents) {
    const container = document.getElementById('playground-agent-cards');
    if (!container) return;

    container.innerHTML = agents
      .map(
        (agent) => `
      <div class="playground-agent-card ${state.currentAgent?.id === agent.id ? 'active' : ''}"
           data-agent-id="${agent.id}">
        <div class="playground-agent-card-header">
          <span class="playground-agent-name">@${agent.id}</span>
          <span class="playground-agent-status online"></span>
        </div>
        <div class="playground-agent-role">${agent.role}</div>
        <div class="playground-agent-skills">${agent.skills.length} skills</div>
      </div>
    `
      )
      .join('');

    // Add click handlers
    container.querySelectorAll('.playground-agent-card').forEach((card) => {
      card.addEventListener('click', () => {
        const agentId = card.dataset.agentId;
        selectAgent(agentId);
      });
    });
  }

  function renderSkillsCheckboxes(skills, enabledSkills) {
    const container = document.getElementById('playground-skills-checkboxes');
    if (!container) return;

    container.innerHTML = skills
      .map(
        (skill) => `
      <label class="playground-skill-checkbox">
        <input type="checkbox"
               value="${skill.name}"
               ${enabledSkills.includes(skill.name) ? 'checked' : ''}>
        <span>${skill.name}</span>
      </label>
    `
      )
      .join('');

    // Add change handlers
    container.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
      checkbox.addEventListener('change', () => {
        updateEnabledSkills();
      });
    });
  }

  function renderSkillSelector(skills) {
    const select = document.getElementById('playground-skill-select');
    if (!select) return;

    select.innerHTML =
      '<option value="">-- Select a skill --</option>' +
      skills.map((skill) => `<option value="${skill.name}">${skill.name}</option>`).join('');
  }

  function renderSkillActions(skill) {
    const container = document.getElementById('playground-skill-actions');
    if (!container || !skill) {
      container.innerHTML = '';
      return;
    }

    container.innerHTML = `
      <div class="playground-action-list">
        ${skill.actions
          .map(
            (action) => `
          <label class="playground-action-item ${action.is_destructive ? 'destructive' : ''}">
            <input type="radio" name="skill-action" value="${action.name}">
            <span>${action.name}</span>
            ${action.is_destructive ? '<span class="warning-badge">destructive</span>' : ''}
          </label>
        `
          )
          .join('')}
      </div>
    `;

    // Add change handlers
    container.querySelectorAll('input[type="radio"]').forEach((radio) => {
      radio.addEventListener('change', () => {
        const actionName = radio.value;
        const action = skill.actions.find((a) => a.name === actionName);
        renderSkillParams(action);
        document.getElementById('playground-execute-skill').disabled = false;
      });
    });
  }

  function renderSkillParams(action) {
    const container = document.getElementById('playground-skill-params');
    if (!container || !action || !action.input_schema) {
      container.innerHTML = '';
      return;
    }

    const properties = action.input_schema.properties || {};
    const required = action.input_schema.required || [];

    container.innerHTML = Object.entries(properties)
      .map(
        ([name, schema]) => `
      <label class="field">
        <span>${name}${required.includes(name) ? ' *' : ''}</span>
        ${renderParamInput(name, schema)}
      </label>
    `
      )
      .join('');
  }

  function renderParamInput(name, schema) {
    const type = schema.type || 'string';
    const description = schema.description || '';

    if (type === 'boolean') {
      return `<input type="checkbox" name="${name}" title="${description}">`;
    }

    if (type === 'integer' || type === 'number') {
      return `<input type="number" name="${name}" placeholder="${description}" title="${description}">`;
    }

    if (schema.enum) {
      return `
        <select name="${name}" title="${description}">
          ${schema.enum.map((v) => `<option value="${v}">${v}</option>`).join('')}
        </select>
      `;
    }

    return `<input type="text" name="${name}" placeholder="${description}" title="${description}">`;
  }

  function addMessage(role, content, metadata = {}) {
    const container = document.getElementById('playground-messages');
    if (!container) return;

    // Remove empty state
    const emptyState = container.querySelector('.playground-empty-state');
    if (emptyState) emptyState.remove();

    const messageEl = document.createElement('div');
    messageEl.className = `playground-message ${role}`;

    if (role === 'tool') {
      messageEl.innerHTML = `
        <div class="playground-tool-call">
          <span class="tool-icon">⚙️</span>
          <span class="tool-name">${metadata.tool || 'tool'}</span>
          <span class="tool-duration">${metadata.duration_ms || 0}ms</span>
        </div>
      `;
    } else {
      messageEl.innerHTML = `
        <div class="playground-message-header">
          <span class="playground-message-role">${role === 'user' ? 'You' : '@' + state.currentAgent?.id}</span>
        </div>
        <div class="playground-message-content">${formatContent(content)}</div>
      `;
    }

    container.appendChild(messageEl);
    container.scrollTop = container.scrollHeight;
  }

  function formatContent(content) {
    // Use the shared markdown parser from app.js if available
    if (typeof window.parseMarkdown === 'function') {
      return window.parseMarkdown(content);
    }
    // Fallback to basic formatting
    return content
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`(.*?)`/g, '<code>$1</code>')
      .replace(/\n/g, '<br>');
  }

  function updateStats(tokens, cost) {
    state.totalTokens += tokens;
    state.totalCost += cost;

    const tokenEl = document.getElementById('playground-token-count');
    const costEl = document.getElementById('playground-cost');

    if (tokenEl) tokenEl.textContent = `Tokens: ${state.totalTokens.toLocaleString()}`;
    if (costEl) costEl.textContent = `Cost: $${state.totalCost.toFixed(4)}`;
  }

  function updateStateView() {
    const stateView = document.getElementById('playground-state-view');
    if (stateView) {
      stateView.textContent = JSON.stringify(
        {
          sessionId: state.sessionId,
          agent: state.currentAgent?.id,
          messages: state.messages.length,
          tokens: state.totalTokens,
          cost: state.totalCost,
        },
        null,
        2
      );
    }

    const historyContainer = document.getElementById('playground-message-history');
    if (historyContainer) {
      historyContainer.innerHTML = state.messages
        .map(
          (msg, i) => `
        <div class="playground-history-item">
          <span class="history-role">[${msg.role}]</span>
          <span class="history-preview">${msg.content.slice(0, 50)}...</span>
        </div>
      `
        )
        .join('');
    }
  }

  // ============================================================================
  // Event Handlers
  // ============================================================================

  function selectAgent(agentId) {
    const agent = state.agents.find((a) => a.id === agentId);
    if (!agent) return;

    state.currentAgent = agent;
    state.sessionId = null; // New session
    state.messages = [];
    state.totalTokens = 0;
    state.totalCost = 0;

    // Update UI
    renderAgentCards(state.agents);

    // Update chat panel
    document.getElementById('playground-chat-title').textContent = `Chatting with @${agentId}`;
    document.getElementById('playground-agent-prefix').textContent = `@${agentId}`;
    document.getElementById('playground-input').disabled = false;
    document.getElementById('playground-send').disabled = false;

    // Clear messages
    const messagesContainer = document.getElementById('playground-messages');
    messagesContainer.innerHTML = `
      <div class="playground-welcome">
        <p>You're now chatting with <strong>@${agentId}</strong></p>
        <p>${agent.description}</p>
        <p>Available skills: ${agent.skills.join(', ')}</p>
      </div>
    `;

    // Update config
    state.config.model = agent.default_model;
    state.config.temperature = agent.default_temperature;
    state.config.enabledSkills = [...agent.skills];

    document.getElementById('playground-model').value = agent.default_model;
    document.getElementById('playground-temperature').value = agent.default_temperature;
    document.getElementById('playground-temp-value').textContent = agent.default_temperature;

    renderSkillsCheckboxes(state.skills, state.config.enabledSkills);

    // Update config title
    document.getElementById('playground-config-title').textContent = `@${agentId} Configuration`;

    // Reset stats
    updateStats(0, 0);
    state.totalTokens = 0;
    state.totalCost = 0;
    updateStateView();
  }

  function updateEnabledSkills() {
    const checkboxes = document.querySelectorAll('#playground-skills-checkboxes input[type="checkbox"]');
    state.config.enabledSkills = Array.from(checkboxes)
      .filter((cb) => cb.checked)
      .map((cb) => cb.value);
  }

  async function handleSendMessage() {
    const input = document.getElementById('playground-input');
    const message = input.value.trim();

    if (!message || !state.currentAgent) return;

    // Add user message to UI
    addMessage('user', message);
    state.messages.push({ role: 'user', content: message });
    input.value = '';

    // Disable input while processing
    input.disabled = true;
    document.getElementById('playground-send').disabled = true;

    try {
      const config = {
        model: state.config.model,
        temperature: state.config.temperature,
        max_tokens: state.config.maxTokens,
        skills: state.config.enabledSkills,
      };

      if (state.config.systemPromptOverride) {
        config.system_prompt_override = state.config.systemPromptOverride;
      }

      const response = await sendMessage(state.currentAgent.id, message, config);

      // Handle SSE streaming
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let responseContent = '';
      let currentMessageEl = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;

          try {
            const event = JSON.parse(line.slice(6));

            switch (event.type) {
              case 'message_start':
                state.sessionId = event.data.session_id;
                currentMessageEl = document.createElement('div');
                currentMessageEl.className = 'playground-message assistant';
                currentMessageEl.innerHTML = `
                  <div class="playground-message-header">
                    <span class="playground-message-role">@${state.currentAgent.id}</span>
                  </div>
                  <div class="playground-message-content"></div>
                `;
                document.getElementById('playground-messages').appendChild(currentMessageEl);
                break;

              case 'message_delta':
                responseContent = event.data.content || '';
                if (currentMessageEl) {
                  const contentEl = currentMessageEl.querySelector('.playground-message-content');
                  if (contentEl) contentEl.innerHTML = formatContent(responseContent);
                }
                break;

              case 'tool_start':
                addMessage('tool', '', {
                  tool: `${event.data.tool}(${JSON.stringify(event.data.args)})`,
                  duration_ms: '...',
                });
                break;

              case 'tool_end':
                // Update the last tool message with timing
                const toolMessages = document.querySelectorAll('.playground-message.tool');
                if (toolMessages.length > 0) {
                  const lastTool = toolMessages[toolMessages.length - 1];
                  const durationEl = lastTool.querySelector('.tool-duration');
                  if (durationEl) durationEl.textContent = `${event.data.duration_ms}ms`;
                }
                break;

              case 'message_end':
                updateStats(event.data.tokens || 0, event.data.cost_usd || 0);
                state.messages.push({ role: 'assistant', content: responseContent });
                updateStateView();
                break;

              case 'error':
                addMessage('assistant', `Error: ${event.data.error}`);
                break;
            }
          } catch (e) {
            // Ignore parse errors for incomplete chunks
          }
        }
      }
    } catch (error) {
      addMessage('assistant', `Error: ${error.message}`);
    } finally {
      input.disabled = false;
      document.getElementById('playground-send').disabled = false;
      input.focus();
    }
  }

  async function handleExecuteSkill() {
    const skillSelect = document.getElementById('playground-skill-select');
    const skillName = skillSelect.value;

    const actionRadio = document.querySelector('input[name="skill-action"]:checked');
    if (!actionRadio) {
      alert('Please select an action');
      return;
    }

    const actionName = actionRadio.value;

    // Gather params
    const params = {};
    document.querySelectorAll('#playground-skill-params input, #playground-skill-params select').forEach((input) => {
      if (input.type === 'checkbox') {
        params[input.name] = input.checked;
      } else if (input.value) {
        params[input.name] = input.type === 'number' ? Number(input.value) : input.value;
      }
    });

    const resultEl = document.getElementById('playground-skill-result');
    const timingEl = document.getElementById('playground-skill-timing');

    resultEl.textContent = 'Executing...';
    timingEl.textContent = '';

    try {
      const result = await executeSkill(skillName, actionName, params);

      resultEl.textContent = JSON.stringify(result.result, null, 2);
      timingEl.textContent = result.success
        ? `✓ Success (${result.duration_ms}ms)`
        : `✗ Failed: ${result.error}`;
      timingEl.className = result.success
        ? 'playground-skill-timing success'
        : 'playground-skill-timing error';
    } catch (error) {
      resultEl.textContent = JSON.stringify({ error: error.message }, null, 2);
      timingEl.textContent = `✗ Error: ${error.message}`;
      timingEl.className = 'playground-skill-timing error';
    }
  }

  // ============================================================================
  // Tab Switching
  // ============================================================================

  function switchPlaygroundTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.playground-tab').forEach((tab) => {
      tab.classList.toggle('active', tab.dataset.tab === tabName);
    });

    // Update tab content
    document.querySelectorAll('.playground-tab-content').forEach((content) => {
      content.hidden = content.dataset.tab !== tabName;
      content.classList.toggle('active', content.dataset.tab === tabName);
    });
  }

  // ============================================================================
  // Initialization
  // ============================================================================

  async function initPlayground() {
    // Load agents
    state.agents = await fetchAgents();
    renderAgentCards(state.agents);

    // Load skills
    state.skills = await fetchSkills();
    renderSkillSelector(state.skills);

    // Bind event handlers
    document.getElementById('playground-send')?.addEventListener('click', handleSendMessage);

    document.getElementById('playground-input')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSendMessage();
      }
    });

    document.getElementById('playground-temperature')?.addEventListener('input', (e) => {
      state.config.temperature = parseFloat(e.target.value);
      document.getElementById('playground-temp-value').textContent = state.config.temperature;
    });

    document.getElementById('playground-model')?.addEventListener('change', (e) => {
      state.config.model = e.target.value;
    });

    document.getElementById('playground-max-tokens')?.addEventListener('change', (e) => {
      state.config.maxTokens = parseInt(e.target.value);
    });

    document.getElementById('playground-system-prompt')?.addEventListener('change', (e) => {
      state.config.systemPromptOverride = e.target.value || null;
    });

    document.getElementById('playground-clear')?.addEventListener('click', () => {
      state.messages = [];
      state.totalTokens = 0;
      state.totalCost = 0;
      const container = document.getElementById('playground-messages');
      if (container && state.currentAgent) {
        container.innerHTML = `
          <div class="playground-welcome">
            <p>Conversation cleared. Ready to chat with <strong>@${state.currentAgent.id}</strong></p>
          </div>
        `;
      }
      updateStats(0, 0);
      state.totalTokens = 0;
      state.totalCost = 0;
      updateStateView();
    });

    document.getElementById('playground-copy-state')?.addEventListener('click', () => {
      const stateView = document.getElementById('playground-state-view');
      navigator.clipboard.writeText(stateView.textContent);
    });

    document.getElementById('playground-skill-select')?.addEventListener('change', async (e) => {
      const skillName = e.target.value;
      if (!skillName) {
        renderSkillActions(null);
        document.getElementById('playground-execute-skill').disabled = true;
        return;
      }

      // Fetch skill details
      try {
        const response = await fetch(`/playground/skills/${skillName}`);
        const skill = await response.json();
        renderSkillActions(skill);
      } catch (error) {
        console.error('Error fetching skill:', error);
      }
    });

    document.getElementById('playground-execute-skill')?.addEventListener('click', handleExecuteSkill);

    // Tab switching
    document.querySelectorAll('.playground-tab').forEach((tab) => {
      tab.addEventListener('click', () => switchPlaygroundTab(tab.dataset.tab));
    });

    // Preset saving (simplified)
    document.getElementById('playground-save-preset')?.addEventListener('click', async () => {
      const name = prompt('Enter preset name:');
      if (!name) return;

      try {
        await fetch('/playground/presets', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name,
            agent_id: state.currentAgent?.id || 'triage',
            config: state.config,
          }),
        });
        alert('Preset saved!');
      } catch (error) {
        alert('Failed to save preset: ' + error.message);
      }
    });

    console.log('Playground initialized');
  }

  // Export for use in app.js
  window.playgroundInit = initPlayground;
  window.switchPlaygroundTab = switchPlaygroundTab;
})();
