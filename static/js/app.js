/* ==========================================================================
   ShareLoop Frontend Controller (static/js/app.js)
   Full-Stack SPA Controller for templates/index.html & templates/login.html
   ========================================================================== */

let currentUser = window.SHARELOOP_INITIAL_USER || window.SHARELOOP_USER || null;
let currentView = 'browse';
let browseItemsList = [];
let myListingsList = [];
let myRequestsList = [];
let incomingRequestsList = [];
let feedRequestsList = [];
let currentInspectItem = null;
let currentInspectRequest = null;
let pendingConfirmCallback = null;
let cachedAdminOverview = null;
let selectedAdminTxStatus = 'All';
let cachedAdminActiveAccounts = [];
let selectedActiveAccountRoleFilter = 'Student';

const CATEGORY_TAXONOMY = {
  'School Education': [
    'Primary (Class 1-5)',
    'Lower Secondary (Class 6-8)',
    'Secondary (9-10)',
    'Higher Secondary (Class 11-12)'
  ],
  'Higher Education': [
    'Science, Tech & Engineering (STEM)',
    'Business, Management & Economics',
    'Humanities, Arts & Social Sciences',
    'Medicine, Health & Life Sciences'
  ],
  'Equipment & Gear': [
    'Lab Gear & Equipment',
    'Stationeries & School Supplies'
  ],
  'Others': [
    'Others'
  ]
};

const NEPALI_PHONE_DASH_REGEX = /^(?:\(\+977\)\s*|\+977[\s\-]?)?([0-9]{10})$/;

// --------------------------------------------------------------------------
// 1. INITIALIZATION
// --------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  if (window.SHARELOOP_INITIAL_USER) {
    currentUser = window.SHARELOOP_INITIAL_USER;
  }

  initCategoryComboboxes();
  syncUserHeaderAndComposer();

  // Close category dropdowns when clicking outside
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.searchable-combobox')) {
      document.querySelectorAll('.combobox-dropdown').forEach(el => el.classList.add('hidden'));
    }
  });

  if (currentUser && currentUser.role === 'Admin') {
    navigateTo('admin-overview');
  } else if (currentUser) {
    navigateTo('browse');
    loadAllRequests();
    if (currentUser.role === 'Student') {
      loadFeedWorkspace();
    }
  }
});

function getFirstName(userObj) {
  if (!userObj) return 'Student';
  if (userObj.first_name && userObj.first_name.trim()) {
    return userObj.first_name.trim();
  }
  const full = (userObj.name || '').trim();
  if (!full) return 'Student';
  return full.split(/\s+/)[0];
}

function syncUserHeaderAndComposer() {
  if (!currentUser) return;

  const initialsEl = document.getElementById('topbar-user-initials');
  const nameEl = document.getElementById('topbar-user-name');
  const roleBadge = document.getElementById('topbar-role-badge');
  const sidebarRoleTitle = document.getElementById('sidebar-role-title');
  const sidebarUni = document.getElementById('sidebar-university');

  if (initialsEl) initialsEl.textContent = currentUser.initials || 'U';
  if (nameEl) nameEl.textContent = currentUser.name || '';
  if (roleBadge) roleBadge.textContent = `${currentUser.role || 'Student'} Portal`;
  if (sidebarRoleTitle) sidebarRoleTitle.textContent = `${currentUser.role || 'Student'} Account`;
  if (sidebarUni) sidebarUni.textContent = currentUser.university || '';

  const feedAvatar = document.getElementById('feed-composer-avatar');
  const feedComposerInput = document.getElementById('feed-composer-trigger-input');
  if (feedAvatar) {
    feedAvatar.textContent = currentUser.initials || 'ST';
  }
  if (feedComposerInput) {
    feedComposerInput.placeholder = `What's on your mind, ${getFirstName(currentUser)}?`;
  }
}

// --------------------------------------------------------------------------
// 2. TOAST & SAFE OPERATIONAL CONFIRMATION MODAL
// --------------------------------------------------------------------------
let toastTimeout = null;
function showToast(message, isError = false) {
  const toast = document.getElementById('toast-notification');
  if (!toast) return;
  toast.textContent = message;
  toast.className = isError ? 'toast error' : 'toast';
  toast.classList.remove('hidden');

  if (toastTimeout) clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => {
    toast.classList.add('hidden');
  }, 3800);
}

function openConfirmModal(message, acceptLabel, onConfirm) {
  const backdrop = document.getElementById('confirm-modal-backdrop');
  const msgEl = document.getElementById('confirm-modal-message');
  const acceptBtn = document.getElementById('confirm-modal-accept-btn');
  if (!backdrop || !msgEl || !acceptBtn) return;

  msgEl.textContent = message;
  acceptBtn.textContent = acceptLabel || 'Confirm';
  pendingConfirmCallback = onConfirm;
  backdrop.classList.remove('hidden');
}

function closeConfirmModal() {
  const backdrop = document.getElementById('confirm-modal-backdrop');
  if (backdrop) backdrop.classList.add('hidden');
  pendingConfirmCallback = null;
}

function executeConfirmedAction() {
  const cb = pendingConfirmCallback;
  closeConfirmModal();
  if (typeof cb === 'function') {
    cb();
  }
}

function requestLogoutConfirmation() {
  openConfirmModal('Are you sure you want to log out of your ShareLoop account?', 'Logout', performLogout);
}

async function performLogout() {
  try {
    const res = await fetch('/api/auth/logout', { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    const emailToSave = data.last_email || (currentUser && currentUser.email) || '';
    if (emailToSave) {
      sessionStorage.setItem('shareloop_last_logout_email', emailToSave);
    }
  } catch (err) {
    if (currentUser && currentUser.email) {
      sessionStorage.setItem('shareloop_last_logout_email', currentUser.email);
    }
  }
  window.location.href = '/login';
}

// --------------------------------------------------------------------------
// 3. CORE SPA NAVIGATION ENGINE
// --------------------------------------------------------------------------
function navigateTo(viewName) {
  currentView = viewName;

  document.querySelectorAll('.view-section').forEach(sec => {
    sec.classList.add('hidden');
  });

  document.querySelectorAll('.sidebar-nav .nav-item').forEach(btn => {
    btn.classList.remove('active');
  });

  const navMap = {
    'browse': 'nav-browse',
    'feed': 'nav-feed',
    'my-listings': 'nav-my-listings',
    'add-resource': 'nav-my-listings',
    'my-requests': 'nav-my-requests',
    'incoming': 'nav-incoming',
    'profile': 'nav-profile',
    'security': 'nav-security',
    'admin-overview': 'nav-admin-overview',
    'admin-resources': 'nav-admin-resources',
    'admin-transactions': 'nav-admin-transactions',
    'admin-active-accounts': 'nav-admin-active-accounts',
    'admin-pending-accounts': 'nav-admin-pending-accounts'
  };

  const activeNavId = navMap[viewName];
  if (activeNavId) {
    const navBtn = document.getElementById(activeNavId);
    if (navBtn) navBtn.classList.add('active');
  }

  const targetSection = document.getElementById(`view-${viewName}`);
  if (targetSection) {
    targetSection.classList.remove('hidden');
  }

  // Trigger contextual data fetch
  if (viewName === 'browse') {
    loadBrowseItems();
  } else if (viewName === 'feed') {
    syncUserHeaderAndComposer();
    loadFeedWorkspace();
  } else if (viewName === 'my-listings') {
    loadMyListings();
  } else if (viewName === 'my-requests' || viewName === 'incoming') {
    loadAllRequests();
  } else if (viewName === 'admin-overview') {
    loadAdminOverview();
    loadAdminPendingAccountsBadgeOnly();
  } else if (viewName === 'admin-resources') {
    loadAdminResources();
  } else if (viewName === 'admin-transactions') {
    loadAdminTransactions();
  } else if (viewName === 'admin-active-accounts') {
    loadAdminActiveAccounts();
  } else if (viewName === 'admin-pending-accounts') {
    loadAdminPendingAccounts();
  }
}

const switchView = navigateTo;

function handleSidebarNavWithDrawer(viewName, drawerContext) {
  if (currentView === viewName && drawerContext) {
    toggleFilterDrawer(drawerContext);
    return;
  }
  navigateTo(viewName);
}

function toggleFilterDrawer(context, forceOpen = null) {
  const isAdminCtx = context === 'admin';
  const drawerId = isAdminCtx ? 'admin-filter-drawer' : 'browse-filter-drawer';
  const layoutId = isAdminCtx ? 'admin-resources-layout-container' : 'browse-layout-container';
  const btnId = isAdminCtx ? 'admin-filter-toggle-btn' : 'browse-filter-toggle-btn';

  const drawer = document.getElementById(drawerId);
  const layout = document.getElementById(layoutId);
  const btn = document.getElementById(btnId);
  if (!drawer) return;

  const isCurrentlyHidden = drawer.classList.contains('hidden');
  const shouldOpen = forceOpen !== null ? Boolean(forceOpen) : isCurrentlyHidden;

  if (shouldOpen) {
    drawer.classList.remove('hidden');
    if (layout) {
      layout.classList.remove('drawer-closed');
      layout.classList.add('drawer-open');
    }
    if (btn) {
      btn.textContent = 'Hide Filters';
      btn.setAttribute('aria-expanded', 'true');
    }
  } else {
    drawer.classList.add('hidden');
    if (layout) {
      layout.classList.remove('drawer-open');
      layout.classList.add('drawer-closed');
    }
    if (btn) {
      btn.textContent = 'Show Filters';
      btn.setAttribute('aria-expanded', 'false');
    }
  }
}

let searchDebounceTimer = null;
function handleSearchInput() {
  clearTimeout(searchDebounceTimer);
  searchDebounceTimer = setTimeout(() => {
    if (currentUser && currentUser.role === 'Admin') {
      if (currentView !== 'admin-resources') {
        navigateTo('admin-resources');
      } else {
        loadAdminResources();
      }
    } else {
      if (currentView !== 'browse') {
        navigateTo('browse');
      } else {
        loadBrowseItems();
      }
    }
  }, 220);
}

// --------------------------------------------------------------------------
// 4. SEARCHABLE & SCROLLABLE CATEGORY COMBOBOXES ('res' & 'feed')
// --------------------------------------------------------------------------
function initCategoryComboboxes() {
  renderCategoryDropdownOptions('res', '');
  renderCategoryDropdownOptions('feed', '');
}

function renderCategoryDropdownOptions(prefix, query = '') {
  const dropdown = document.getElementById(`${prefix}-category-dropdown`);
  const hiddenInput = document.getElementById(`${prefix}-category`);
  if (!dropdown) return;

  const selectedValue = hiddenInput ? hiddenInput.value : '';
  const q = (query || '').trim().toLowerCase();
  let html = '';
  let matchesCount = 0;

  Object.entries(CATEGORY_TAXONOMY).forEach(([groupTitle, categories]) => {
    const matchingCats = categories.filter(cat =>
      !q || cat.toLowerCase().includes(q) || groupTitle.toLowerCase().includes(q)
    );
    if (matchingCats.length > 0) {
      matchesCount += matchingCats.length;
      html += `
        <div class="combobox-group">
          <div class="combobox-group-title">${escapeHtml(groupTitle)}</div>
          ${matchingCats.map(cat => {
            const isSelected = cat === selectedValue;
            return `
              <button
                type="button"
                class="combobox-option ${isSelected ? 'selected' : ''}"
                onclick="selectCategoryComboboxOption('${prefix}', '${escapeAttr(cat)}')"
              >
                <span>${escapeHtml(cat)}</span>
                ${isSelected ? '<span class="combobox-check">&#10003;</span>' : ''}
              </button>
            `;
          }).join('')}
        </div>
      `;
    }
  });

  if (matchesCount === 0) {
    html = `<div class="combobox-empty">No matching categories found.</div>`;
  }

  dropdown.innerHTML = html;
}

function openCategoryCombobox(prefix) {
  const dropdown = document.getElementById(`${prefix}-category-dropdown`);
  if (!dropdown) return;
  renderCategoryDropdownOptions(prefix, '');
  dropdown.classList.remove('hidden');
}

function toggleCategoryCombobox(prefix) {
  const dropdown = document.getElementById(`${prefix}-category-dropdown`);
  if (!dropdown) return;
  if (dropdown.classList.contains('hidden')) {
    renderCategoryDropdownOptions(prefix, '');
    dropdown.classList.remove('hidden');
  } else {
    dropdown.classList.add('hidden');
  }
}

function filterCategoryCombobox(prefix, query) {
  const dropdown = document.getElementById(`${prefix}-category-dropdown`);
  if (!dropdown) return;
  renderCategoryDropdownOptions(prefix, query);
  dropdown.classList.remove('hidden');
}

function selectCategoryComboboxOption(prefix, categoryValue) {
  const hiddenInput = document.getElementById(`${prefix}-category`);
  const searchInput = document.getElementById(`${prefix}-category-search`);
  const dropdown = document.getElementById(`${prefix}-category-dropdown`);

  if (hiddenInput) hiddenInput.value = categoryValue;
  if (searchInput) searchInput.value = categoryValue;
  if (dropdown) dropdown.classList.add('hidden');
}

// --------------------------------------------------------------------------
// 5. BROWSE EXCHANGE & MULTI-SELECT FILTER PANEL
// --------------------------------------------------------------------------
function filterSidebarCategoryList(query) {
  const scrollbox = document.getElementById('filter-category-scrollbox');
  if (!scrollbox) return;
  const q = (query || '').trim().toLowerCase();

  scrollbox.querySelectorAll('.category-filter-group').forEach(group => {
    let visibleCount = 0;
    group.querySelectorAll('.category-filter-item').forEach(item => {
      const label = (item.dataset.label || item.textContent || '').toLowerCase();
      if (!q || label.includes(q)) {
        item.style.display = 'flex';
        visibleCount++;
      } else {
        item.style.display = 'none';
      }
    });
    group.style.display = visibleCount > 0 ? 'block' : 'none';
  });
}

function resetAllFilters() {
  document.querySelectorAll('.filter-category, .filter-condition').forEach(cb => {
    cb.checked = false;
  });
  document.querySelectorAll('.filter-exchange').forEach(cb => {
    if (currentUser && currentUser.role === 'Organization' && cb.value === 'Donate') {
      cb.checked = true;
    } else {
      cb.checked = false;
    }
  });
  const availOnly = document.getElementById('filter-available-only');
  if (availOnly) availOnly.checked = true;

  const catSearch = document.getElementById('filter-category-search');
  if (catSearch) {
    catSearch.value = '';
    filterSidebarCategoryList('');
  }
  const globalSearch = document.getElementById('global-search-input');
  if (globalSearch) globalSearch.value = '';

  loadBrowseItems();
}

async function loadBrowseItems() {
  const grid = document.getElementById('browse-items-grid');
  if (!grid) return;

  const search = (document.getElementById('global-search-input')?.value || '').trim();
  const selectedExchanges = Array.from(document.querySelectorAll('.filter-exchange:checked')).map(el => el.value);
  const selectedCategories = Array.from(document.querySelectorAll('.filter-category:checked')).map(el => el.value);
  const selectedConditions = Array.from(document.querySelectorAll('.filter-condition:checked')).map(el => el.value);
  const availableOnly = document.getElementById('filter-available-only')?.checked ?? false;

  const params = new URLSearchParams();
  if (search) params.set('search', search);
  if (selectedExchanges.length) params.set('exchange_types', selectedExchanges.join(','));
  if (selectedCategories.length) params.set('categories', selectedCategories.join('||'));
  if (selectedConditions.length) params.set('conditions', selectedConditions.join(','));
  if (availableOnly) params.set('available_only', 'true');

  try {
    const res = await fetch(`/api/items?${params.toString()}`);
    if (!res.ok) return;
    const data = await res.json();
    browseItemsList = data.items || [];

    if (browseItemsList.length === 0) {
      grid.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1;">
          <h3>No matching resources found</h3>
          <p>Try clearing some filters or searching for another textbook, course code, or lab item.</p>
          <button type="button" class="btn-outline btn-sm" onclick="resetAllFilters()">Reset Filters</button>
        </div>
      `;
      return;
    }

    grid.innerHTML = browseItemsList.map(item => renderBrowseItemCard(item)).join('');
  } catch (err) {
    console.error('Error loading browse items:', err);
  }
}

function getExchangeBadgeClass(exchangeType) {
  if (exchangeType === 'Donate') return 'badge-green';
  if (exchangeType === 'Swap') return 'badge-amber';
  return 'badge-blue';
}

function renderBrowseItemCard(item) {
  const isMine = currentUser && item.owner_id === currentUser.id;
  const ownerName = item.owner ? item.owner.name : 'Campus Peer';
  const exchangeClass = getExchangeBadgeClass(item.exchange_type);

  return `
    <article class="item-card" onclick="openItemDetails(${item.id})">
      <div>
        <div class="item-card-image-wrap">
          <img src="${escapeHtml(item.image_url)}" alt="${escapeHtml(item.title)}" loading="lazy" />
          <div class="item-card-badges">
            <span class="badge ${exchangeClass}">${escapeHtml(item.exchange_type)}</span>
            <span class="badge badge-neutral">${escapeHtml(item.condition)}</span>
          </div>
        </div>
        <div class="item-card-body">
          <div class="item-card-meta">
            <span class="course-tag">${escapeHtml(item.course_code || 'GEN 101')}</span>
            <span class="category-tag">${escapeHtml(item.category)}</span>
          </div>
          <h3 class="item-card-title">${escapeHtml(item.title)}</h3>
          <p class="item-card-author">${escapeHtml(item.author)}</p>
          <p class="item-card-owner">
            Shared by <strong>${escapeHtml(ownerName)}</strong>
            ${isMine ? '<span class="mine-tag">(You)</span>' : ''}
          </p>
        </div>
      </div>
      <div class="item-card-footer">
        <span class="status-pill ${item.is_available ? 'available' : 'unavailable'}">
          ${item.is_available ? '● Available' : '○ Unavailable'}
        </span>
        <span class="link-btn">View Details &rarr;</span>
      </div>
    </article>
  `;
}

// --------------------------------------------------------------------------
// 6. ITEM DETAILS & 4-SLOT PHOTO GALLERY INSPECT VIEW
// --------------------------------------------------------------------------
async function openItemDetails(itemId, returnView = null) {
  try {
    const res = await fetch(`/api/items/${itemId}`);
    if (!res.ok) {
      showToast('Could not load item details.', true);
      return;
    }
    const data = await res.json();
    const item = data.item || data;
    currentInspectItem = item;

    const backBtn = document.getElementById('item-details-back-btn');
    if (backBtn) {
      if (currentUser && currentUser.role === 'Admin') {
        backBtn.innerHTML = '&larr; Back to Resource Feed';
        backBtn.onclick = () => navigateTo('admin-resources');
      } else if (returnView) {
        backBtn.innerHTML = '&larr; Back';
        backBtn.onclick = () => navigateTo(returnView);
      } else {
        const label = currentUser && currentUser.role === 'Organization' ? 'Listings' : 'Browse Exchange';
        backBtn.innerHTML = `&larr; Back to ${label}`;
        backBtn.onclick = () => navigateTo('browse');
      }
    }

    renderItemDetails(item);

    document.querySelectorAll('.view-section').forEach(sec => sec.classList.add('hidden'));
    const section = document.getElementById('view-item-details');
    if (section) section.classList.remove('hidden');
  } catch (err) {
    console.error('Error opening item details:', err);
  }
}

function switchDetailGalleryPhoto(photoUrl, thumbBtn) {
  const mainImg = document.getElementById('detail-primary-photo');
  if (mainImg && photoUrl) {
    mainImg.src = photoUrl;
  }
  document.querySelectorAll('.detail-gallery-thumb').forEach(btn => {
    btn.style.borderColor = '#E5E7EB';
  });
  if (thumbBtn) {
    thumbBtn.style.borderColor = '#1B3B2B';
  }
}

function renderItemDetails(item) {
  const container = document.getElementById('item-details-container');
  if (!container) return;

  const isOwner = currentUser && item.owner_id === currentUser.id;
  const isAdmin = currentUser && currentUser.role === 'Admin';
  const owner = item.owner || {};

  const photoSlots = [
    { label: '1. Main Photo', url: item.front_cover_path || item.image_url },
    { label: '2. Back / Side View', url: item.back_cover_path },
    { label: '3. Detail / Defect Zoom', url: item.spine_path },
    { label: '4. Additional View', url: item.inside_pages_path }
  ].filter(slot => slot.url && slot.url.trim() !== '');

  const primaryPhoto = photoSlots.length > 0 ? photoSlots[0].url : item.image_url;

  let actionAreaHTML = '';
  if (isAdmin) {
    // Admin review mode: strip "Request This Resource" and "Mark Available"; show only Delete Listing
    actionAreaHTML = `
      <div class="detail-actions-row">
        <button type="button" class="btn-danger" onclick="confirmDeleteItem(${item.id})">
          Delete Listing
        </button>
      </div>
    `;
  } else if (isOwner) {
    actionAreaHTML = `
      <div class="detail-actions-row">
        <button type="button" class="btn-primary" onclick="openEditResourceView(${item.id})">
          Edit Listing
        </button>
        <button type="button" class="btn-danger" onclick="confirmDeleteItem(${item.id})">
          Delete Listing
        </button>
      </div>
    `;
  } else if (!item.is_available) {
    actionAreaHTML = `
      <div class="unavailable-banner">
        This resource is currently marked as Unavailable.
      </div>
    `;
  } else {
    actionAreaHTML = `
      <div class="request-compose-box">
        <label for="detail-request-notes">Pickup &amp; Coordination Note (Optional)</label>
        <textarea
          id="detail-request-notes"
          rows="3"
          placeholder="Hi ${escapeHtml(owner.name || 'there')}! When and where on campus works best for pickup?"
        ></textarea>
        <button type="button" id="detail-request-submit-btn" class="btn-primary btn-full" onclick="handleCreateExchangeRequest(${item.id})">
          Request This Resource (${escapeHtml(item.exchange_type)})
        </button>
      </div>
    `;
  }

  container.innerHTML = `
    <div class="detail-grid">
      <div class="detail-left">
        <div class="detail-image-card">
          <img id="detail-primary-photo" src="${escapeHtml(primaryPhoto)}" alt="${escapeHtml(item.title)}" />
          ${photoSlots.length > 1 ? `
            <div style="display: grid; grid-template-columns: repeat(${photoSlots.length}, 1fr); gap: 8px; margin-top: 12px;">
              ${photoSlots.map((slot, idx) => `
                <button
                  type="button"
                  class="detail-gallery-thumb"
                  onclick="switchDetailGalleryPhoto('${escapeAttr(slot.url)}', this)"
                  style="border: 2px solid ${idx === 0 ? '#1B3B2B' : '#E5E7EB'}; border-radius: 8px; padding: 4px; background: #fff; cursor: pointer; text-align: center;"
                >
                  <img src="${escapeHtml(slot.url)}" alt="${escapeHtml(slot.label)}" style="width: 100%; height: 58px; object-fit: cover; border-radius: 5px; display: block;" />
                  <small style="display: block; font-size: 0.68rem; color: #4B5563; margin-top: 3px; font-weight: 600;">${escapeHtml(slot.label)}</small>
                </button>
              `).join('')}
            </div>
          ` : ''}
        </div>

        <div class="owner-card">
          <span class="section-eyebrow">SHARED BY</span>
          <div class="owner-row">
            <div class="avatar-circle lg">${escapeHtml(owner.initials || 'U')}</div>
            <div>
              <h4>${escapeHtml(owner.name || 'Campus Member')}</h4>
              <p>${escapeHtml(owner.role || 'Student')} ${owner.university ? '• ' + escapeHtml(owner.university) : ''}</p>
              <small>${owner.completed_exchanges ?? 0} Completed Exchanges</small>
            </div>
          </div>
        </div>
      </div>

      <div class="detail-right">
        <div class="detail-spec-card">
          <div class="detail-badges">
            <span class="course-tag">${escapeHtml(item.course_code || 'GEN 101')}</span>
            <span class="badge ${getExchangeBadgeClass(item.exchange_type)}">${escapeHtml(item.exchange_type)}</span>
            <span class="status-pill ${item.is_available ? 'available' : 'unavailable'}">
              ${item.is_available ? '● Available' : '○ Unavailable'}
            </span>
          </div>

          <h1>${escapeHtml(item.title)}</h1>
          <p class="detail-author">By ${escapeHtml(item.author)}</p>

          <div class="spec-table">
            <div class="spec-row">
              <span>Category</span>
              <strong>${escapeHtml(item.category)}</strong>
            </div>
            <div class="spec-row">
              <span>Condition</span>
              <strong>${escapeHtml(item.condition)}</strong>
            </div>
            <div class="spec-row">
              <span>Exchange Mode</span>
              <strong>${escapeHtml(item.exchange_type)}</strong>
            </div>
            <div class="spec-row">
              <span>Listed Date</span>
              <strong>${escapeHtml(item.created_at || 'Recently')}</strong>
            </div>
          </div>

          ${actionAreaHTML}
        </div>

        <div class="detail-desc-card">
          <h3>Resource Description &amp; Notes</h3>
          <p>${escapeHtml(item.description || 'No additional description provided.')}</p>
        </div>
      </div>
    </div>
  `;
}

// --------------------------------------------------------------------------
// 7. STUDENT REQUEST FEED & ASSOCIATED INTERACTION MODALS
// --------------------------------------------------------------------------
function openFeedCreateModal() {
  const backdrop = document.getElementById('feed-create-modal-backdrop');
  if (!backdrop) return;
  backdrop.classList.remove('hidden');

  const titleInput = document.getElementById('feed-title');
  if (titleInput) {
    setTimeout(() => titleInput.focus(), 50);
  }
}

function closeFeedCreateModal() {
  const backdrop = document.getElementById('feed-create-modal-backdrop');
  if (backdrop) {
    backdrop.classList.add('hidden');
  }
}

async function loadFeedWorkspace() {
  const container = document.getElementById('feed-stream-container');
  if (!container) return;

  try {
    const res = await fetch('/api/feed/active');
    if (!res.ok) return;
    const data = await res.json();
    feedRequestsList = data.feed_requests || data.items || [];

    if (feedRequestsList.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <h3>No active campus requests right now</h3>
          <p>Click the status box above to broadcast a textbook, calculator, or lab item you need!</p>
        </div>
      `;
      return;
    }

    container.innerHTML = feedRequestsList.map(post => {
      const isMine = currentUser && post.student_id === currentUser.id;
      return `
        <article class="feed-card">
          <div class="feed-card-top">
            <span class="badge badge-green">${escapeHtml(post.category)}</span>
            <span class="text-muted">${escapeHtml(post.created_at)}</span>
          </div>
          <h3 class="feed-card-title">${escapeHtml(post.title)}</h3>
          <p class="feed-card-desc">${escapeHtml(post.description || 'No additional details specified.')}</p>
          <div class="feed-card-footer">
            <div class="feed-poster-meta">
              <span class="avatar-circle">${escapeHtml(post.student_initials || 'ST')}</span>
              <div>
                <strong style="font-size: 0.86rem; color: #111827; display: block;">
                  ${escapeHtml(post.student_name)}
                  ${isMine ? '<span class="mine-tag">(You)</span>' : ''}
                </strong>
                ${post.student_university ? `<span class="text-muted">${escapeHtml(post.student_university)}</span>` : ''}
              </div>
            </div>
            <div>
              ${isMine
                ? `<span class="badge badge-neutral">Your Active Broadcast</span>`
                : `<button type="button" class="btn-primary btn-sm" onclick="openFeedRespondModal(${post.id})">I Have This</button>`
              }
            </div>
          </div>
        </article>
      `;
    }).join('');
  } catch (err) {
    console.error('Error loading feed workspace:', err);
  }
}

async function handleCreateFeedPost(event) {
  event.preventDefault();
  const titleEl = document.getElementById('feed-title');
  const categoryHidden = document.getElementById('feed-category');
  const categorySearch = document.getElementById('feed-category-search');
  const descEl = document.getElementById('feed-description');
  const submitBtn = document.getElementById('feed-create-submit-btn');

  const title = (titleEl?.value || '').trim();
  const category = (categoryHidden?.value || categorySearch?.value || 'Science, Tech & Engineering (STEM)').trim();
  const description = (descEl?.value || '').trim();

  if (!title || !category) {
    showToast('Please enter both a Requested Item Title and Category.', true);
    return;
  }

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = 'Broadcasting...';
  }

  try {
    const res = await fetch('/api/feed/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, category, description })
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Unable to broadcast request.');
    }

    const form = document.getElementById('feed-create-form');
    if (form) form.reset();
    if (categoryHidden) categoryHidden.value = 'Science, Tech & Engineering (STEM)';
    if (categorySearch) categorySearch.value = 'Science, Tech & Engineering (STEM)';

    closeFeedCreateModal();
    showToast(data.message || 'Your request has been broadcast to the Campus Feed!');
    await loadFeedWorkspace();
  } catch (err) {
    showToast(err.message, true);
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Broadcast Request to Campus Feed';
    }
  }
}

function updateFeedRespondSubmitState() {
  const file1 = document.getElementById('feed-file-front-cover');
  const file2 = document.getElementById('feed-file-back-cover');
  const submitBtn = document.getElementById('feed-respond-submit-btn');
  if (!submitBtn) return;

  const hasSlot1 = file1 && file1.files && file1.files.length > 0;
  const hasSlot2 = file2 && file2.files && file2.files.length > 0;
  submitBtn.disabled = !(hasSlot1 && hasSlot2);
}

function openFeedRespondModal(feedId) {
  const post = feedRequestsList.find(p => p.id === feedId);
  if (!post) return;

  const backdrop = document.getElementById('feed-respond-modal-backdrop');
  const form = document.getElementById('feed-respond-form');
  if (form) form.reset();

  const idInput = document.getElementById('feed-respond-id');
  const catInput = document.getElementById('feed-respond-category');
  const titleInput = document.getElementById('feed-res-title');
  const subEl = document.getElementById('feed-respond-target-sub');

  if (idInput) idInput.value = post.id;
  if (catInput) catInput.value = post.category;
  if (titleInput) titleInput.value = post.title;
  if (subEl) {
    subEl.textContent = `Responding to ${post.student_name}'s request for "${post.title}". Upload direct proof photos from your local device to verify you physically have this item and open a live pickup chat.`;
  }

  ['feed-preview-front-cover', 'feed-preview-back-cover', 'feed-preview-spine', 'feed-preview-inside-pages'].forEach(id => {
    const img = document.getElementById(id);
    if (img) {
      img.src = '';
      img.classList.add('hidden');
    }
  });

  updateFeedRespondSubmitState();

  if (backdrop) {
    backdrop.classList.remove('hidden');
  }
}

function closeFeedRespondModal() {
  const backdrop = document.getElementById('feed-respond-modal-backdrop');
  if (backdrop) backdrop.classList.add('hidden');
}

async function handleFeedRespondSubmit(event) {
  event.preventDefault();
  const feedId = document.getElementById('feed-respond-id')?.value;
  const file1 = document.getElementById('feed-file-front-cover');
  const file2 = document.getElementById('feed-file-back-cover');
  const submitBtn = document.getElementById('feed-respond-submit-btn');

  if (!feedId) return;

  // Dual-Photo Verification Rules: Freeze submission if either Slot 1 or Slot 2 is empty
  if (!file1?.files?.length || !file2?.files?.length) {
    showToast('Dual-Photo Requirement: Both Slot 1 (1. Main Photo) and Slot 2 (2. Back / Side View) are mandatory.', true);
    updateFeedRespondSubmitState();
    return;
  }

  const form = document.getElementById('feed-respond-form');
  const formData = new FormData(form);

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = 'Uploading Proof & Starting Chat...';
  }

  try {
    const res = await fetch(`/api/feed/respond/${feedId}`, {
      method: 'POST',
      body: formData
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to upload proof photos.');
    }

    closeFeedRespondModal();
    showToast(data.message || 'Proof photos verified! Opening pickup coordination chat...');

    await loadFeedWorkspace();
    await loadAllRequests();

    if (data.request && data.request.id) {
      await openRequestDetails(data.request.id);
    } else {
      navigateTo('incoming');
    }
  } catch (err) {
    showToast(err.message, true);
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Upload Proof & Start Pickup Chat';
    }
  }
}

// --------------------------------------------------------------------------
// 8. MY LISTINGS & ADD/EDIT RESOURCE (DUAL-PHOTO MANDATORY UPLOAD)
// --------------------------------------------------------------------------
function previewSelectedFile(inputEl, previewImgId) {
  const previewImg = document.getElementById(previewImgId);
  if (!previewImg) return;

  if (inputEl && inputEl.files && inputEl.files[0]) {
    const reader = new FileReader();
    reader.onload = (e) => {
      previewImg.src = e.target.result;
      previewImg.classList.remove('hidden');
    };
    reader.readAsDataURL(inputEl.files[0]);
  } else {
    previewImg.src = '';
    previewImg.classList.add('hidden');
  }
}

async function loadMyListings() {
  const container = document.getElementById('my-listings-container');
  if (!container) return;

  try {
    const res = await fetch('/api/items?mine_only=true');
    if (!res.ok) return;
    const data = await res.json();
    myListingsList = data.items || [];

    if (myListingsList.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <h3>You haven't listed any study resources yet</h3>
          <p>Share textbooks, lab coats, calculators, or study notes with peers on campus.</p>
          <button type="button" class="btn-primary btn-sm" onclick="openAddResourceView()">+ Add Your First Resource</button>
        </div>
      `;
      return;
    }

    container.innerHTML = myListingsList.map(item => `
      <div class="list-row-card">
        <img src="${escapeHtml(item.image_url)}" alt="${escapeHtml(item.title)}" class="list-row-thumb" />
        <div class="list-row-info">
          <div class="list-row-tags">
            <span class="course-tag">${escapeHtml(item.course_code || 'GEN 101')}</span>
            <span class="badge ${getExchangeBadgeClass(item.exchange_type)}">${escapeHtml(item.exchange_type)}</span>
            <span class="badge badge-neutral">${escapeHtml(item.condition)}</span>
            <span class="status-pill ${item.is_available ? 'available' : 'unavailable'}">
              ${item.is_available ? '● Available' : '○ Unavailable'}
            </span>
          </div>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.author)} • ${escapeHtml(item.category)}</p>
        </div>
        <div class="list-row-actions">
          <button type="button" class="btn-outline btn-sm" onclick="openItemDetails(${item.id}, 'my-listings')">Inspect</button>
          <button type="button" class="btn-outline btn-sm" onclick="openEditResourceView(${item.id})">Edit</button>
          <button type="button" class="btn-danger btn-sm" onclick="confirmDeleteItem(${item.id})">Delete</button>
        </div>
      </div>
    `).join('');
  } catch (err) {
    console.error('Error loading my listings:', err);
  }
}

function openAddResourceView() {
  const form = document.getElementById('resource-form');
  if (form) form.reset();

  document.getElementById('res-id').value = '';
  document.getElementById('resource-form-title').textContent = 'Add a Study Resource';
  document.getElementById('res-submit-btn').textContent = 'Publish Resource';
  document.getElementById('res-category').value = 'Science, Tech & Engineering (STEM)';
  document.getElementById('res-category-search').value = 'Science, Tech & Engineering (STEM)';
  document.getElementById('res-available').checked = true;

  ['preview-front-cover', 'preview-back-cover', 'preview-spine', 'preview-inside-pages'].forEach(id => {
    const img = document.getElementById(id);
    if (img) {
      img.src = '';
      img.classList.add('hidden');
    }
  });

  navigateTo('add-resource');
}

async function openEditResourceView(itemId) {
  try {
    const res = await fetch(`/api/items/${itemId}`);
    if (!res.ok) return;
    const data = await res.json();
    const item = data.item || data;

    const form = document.getElementById('resource-form');
    if (form) form.reset();

    document.getElementById('res-id').value = item.id;
    document.getElementById('resource-form-title').textContent = 'Edit Study Resource';
    document.getElementById('res-submit-btn').textContent = 'Save Changes';
    document.getElementById('res-title').value = item.title || '';
    document.getElementById('res-author').value = item.author || '';
    document.getElementById('res-course').value = item.course_code || '';
    document.getElementById('res-category').value = item.category || 'Science, Tech & Engineering (STEM)';
    document.getElementById('res-category-search').value = item.category || 'Science, Tech & Engineering (STEM)';
    document.getElementById('res-condition').value = item.condition || 'Good';
    document.getElementById('res-exchange').value = item.exchange_type || 'Lend';
    document.getElementById('res-description').value = item.description || '';
    document.getElementById('res-available').checked = Boolean(item.is_available);

    const previewMap = [
      ['preview-front-cover', item.front_cover_path || item.image_url],
      ['preview-back-cover', item.back_cover_path],
      ['preview-spine', item.spine_path],
      ['preview-inside-pages', item.inside_pages_path]
    ];
    previewMap.forEach(([id, url]) => {
      const img = document.getElementById(id);
      if (img) {
        if (url) {
          img.src = url;
          img.classList.remove('hidden');
        } else {
          img.src = '';
          img.classList.add('hidden');
        }
      }
    });

    navigateTo('add-resource');
  } catch (err) {
    console.error('Error loading item for edit:', err);
  }
}

async function handleSaveResource(event) {
  event.preventDefault();
  const itemId = document.getElementById('res-id').value.trim();
  const file1 = document.getElementById('file-front-cover');
  const file2 = document.getElementById('file-back-cover');
  const submitBtn = document.getElementById('res-submit-btn');

  if (!itemId && (!file1?.files?.length || !file2?.files?.length)) {
    showToast('Dual-Photo Requirement: Both Slot 1 (1. Main Photo) and Slot 2 (2. Back / Side View) are mandatory.', true);
    return;
  }

  const form = document.getElementById('resource-form');
  const formData = new FormData(form);
  formData.set('id', itemId);
  formData.set('category', document.getElementById('res-category').value);
  formData.set('is_available', document.getElementById('res-available').checked ? 'true' : 'false');

  submitBtn.disabled = true;
  submitBtn.textContent = 'Saving...';

  try {
    const res = await fetch('/api/items/add-or-edit', {
      method: 'POST',
      body: formData
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to save resource.');
    }

    showToast(data.message || 'Resource saved successfully!');
    navigateTo('my-listings');
  } catch (err) {
    showToast(err.message, true);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = itemId ? 'Save Changes' : 'Publish Resource';
  }
}

function confirmDeleteItem(itemId) {
  openConfirmModal(
    'Are you sure you want to permanently delete this resource listing from ShareLoop?',
    'Delete Listing',
    () => executeDeleteItem(itemId)
  );
}

async function executeDeleteItem(itemId) {
  try {
    const res = await fetch(`/api/items/${itemId}/delete`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Could not delete listing.');
    }
    showToast(data.message || 'Listing removed from the platform.');
    if (currentUser && currentUser.role === 'Admin') {
      if (currentView === 'item-details') {
        navigateTo('admin-resources');
      } else {
        loadAdminResources();
      }
      loadAdminOverview();
    } else {
      navigateTo('my-listings');
    }
  } catch (err) {
    showToast(err.message, true);
  }
}

// --------------------------------------------------------------------------
// 9. EXCHANGE REQUESTS, MESSAGE THREAD LIFECYCLE & CANCELLATION BUTTON
// --------------------------------------------------------------------------
async function handleCreateExchangeRequest(itemId) {
  const notesEl = document.getElementById('detail-request-notes');
  const submitBtn = document.getElementById('detail-request-submit-btn');
  const notes = (notesEl?.value || '').trim();

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = 'Submitting Request...';
  }

  try {
    const res = await fetch('/api/requests/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_id: itemId, notes })
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Could not create request.');
    }

    showToast(data.message || 'Exchange request submitted!');
    await loadAllRequests();
    if (data.request && data.request.id) {
      await openRequestDetails(data.request.id);
    } else {
      navigateTo('my-requests');
    }
  } catch (err) {
    showToast(err.message, true);
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Request This Resource';
    }
  }
}

async function loadAllRequests() {
  try {
    const res = await fetch('/api/requests');
    if (!res.ok) return;
    const data = await res.json();
    myRequestsList = data.my_requests || [];
    incomingRequestsList = data.incoming_requests || [];

    renderRequestsStack('my-requests-container', myRequestsList, 'outgoing');
    renderRequestsStack('incoming-requests-container', incomingRequestsList, 'incoming');
  } catch (err) {
    console.error('Error loading requests:', err);
  }
}

function getRequestStatusBadgeClass(status) {
  if (status === 'Accepted' || status === 'Handover') return 'badge-green';
  if (status === 'Pending') return 'badge-amber';
  if (status === 'Cancelled' || status === 'Declined') return 'badge-red';
  return 'badge-neutral';
}

function renderRequestsStack(containerId, list, mode) {
  const container = document.getElementById(containerId);
  if (!container) return;

  if (list.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <h3>No ${mode === 'outgoing' ? 'outgoing' : 'incoming'} requests yet</h3>
        <p>${mode === 'outgoing'
          ? 'Resources you request from Browse Exchange or broadcast on the Student Request Feed will appear here.'
          : 'When peers request your listings or when you respond to a Campus Feed broadcast, they will appear here.'}</p>
      </div>
    `;
    return;
  }

  container.innerHTML = list.map(req => {
    const item = req.item || {};
    const partner = mode === 'outgoing' ? (req.owner || {}) : (req.requester || {});
    const partnerRoleLabel = mode === 'outgoing' ? 'Owner' : 'Requester';

    return `
      <div class="list-row-card">
        <img src="${escapeHtml(item.image_url || '')}" alt="${escapeHtml(item.title || 'Resource')}" class="list-row-thumb" />
        <div class="list-row-info">
          <div class="list-row-tags">
            <span class="mono-code">${escapeHtml(req.request_code)}</span>
            <span class="badge ${getExchangeBadgeClass(item.exchange_type || 'Lend')}">${escapeHtml(item.exchange_type || 'Lend')}</span>
            <span class="badge ${getRequestStatusBadgeClass(req.status)}">${escapeHtml(req.status)}</span>
            ${req.is_feed_transaction ? '<span class="badge badge-blue">Campus Feed Match</span>' : ''}
          </div>
          <h3>${escapeHtml(item.title || 'Requested Resource')}</h3>
          <p>${partnerRoleLabel}: <strong>${escapeHtml(partner.name || 'Campus Member')}</strong> • Updated ${escapeHtml(req.updated_time || req.created_at)}</p>
        </div>
        <div class="list-row-actions">
          <button type="button" class="btn-primary btn-sm" onclick="openRequestDetails(${req.id})">
            Open Tracker &amp; Chat &rarr;
          </button>
        </div>
      </div>
    `;
  }).join('');
}

async function openRequestDetails(reqId) {
  if (currentUser && currentUser.role === 'Admin') return;

  try {
    const res = await fetch(`/api/requests/${reqId}`);
    if (!res.ok) {
      showToast('Could not load transaction details.', true);
      return;
    }
    const data = await res.json();
    const req = data.request || data;
    currentInspectRequest = req;

    const backBtn = document.getElementById('request-details-back-btn');
    if (backBtn) {
      const targetDeck = (currentUser && req.requester_id === currentUser.id) ? 'my-requests' : 'incoming';
      backBtn.innerHTML = '&larr; Back to Requests';
      backBtn.onclick = () => navigateTo(targetDeck);
    }

    renderRequestDetails(req);

    document.querySelectorAll('.view-section').forEach(sec => sec.classList.add('hidden'));
    const section = document.getElementById('view-request-details');
    if (section) section.classList.remove('hidden');
  } catch (err) {
    console.error('Error opening request details:', err);
  }
}

function renderRequestDetails(req) {
  const container = document.getElementById('request-details-container');
  if (!container || !currentUser || currentUser.role === 'Admin') return;

  const item = req.item || {};
  const requester = req.requester || {};
  const owner = req.owner || {};
  const isRequester = currentUser.id === req.requester_id;
  const isOwner = currentUser.id === req.owner_id;

  const step1Done = true;
  const step2Done = req.status === 'Accepted' || req.status === 'Handover';
  const step3Done = req.status === 'Handover';

  // Lifecycle Action Controls:
  // - Original Student Requester (`isRequester`): prominent Red action button labeled "Cancel Request"
  // - Owner (`isOwner`): Accept / Decline when Pending, Confirm Handover when Accepted
  let lifecycleButtonsHTML = '';
  if (req.status !== 'Handover' && req.status !== 'Cancelled' && req.status !== 'Declined') {
    const buttons = [];

    if (isOwner && req.status === 'Pending') {
      buttons.push(`
        <button type="button" class="btn-primary btn-sm" onclick="handleUpdateRequestStatus(${req.id}, 'Accepted')">
          Accept Request
        </button>
      `);
      buttons.push(`
        <button type="button" class="btn-danger btn-sm" onclick="handleUpdateRequestStatus(${req.id}, 'Declined')">
          Decline
        </button>
      `);
    }

    if ((isOwner || isRequester) && req.status === 'Accepted') {
      buttons.push(`
        <button type="button" class="btn-primary btn-sm" onclick="handleUpdateRequestStatus(${req.id}, 'Handover')">
          Confirm Handover Completed
        </button>
      `);
    }

    if (isRequester) {
      // Explicit requirement: If the active logged-in session user is the original student who posted
      // the broadcast feed item request (or requester), reveal a prominent Red action button labeled "Cancel Request"
      buttons.push(`
        <button type="button" id="btn-cancel-request" class="btn-danger btn-sm" onclick="cancelTransactionRequest(${req.id})">
          Cancel Request
        </button>
      `);
    }

    if (buttons.length > 0) {
      lifecycleButtonsHTML = `
        <div class="lifecycle-actions">
          ${buttons.join('')}
        </div>
      `;
    }
  }

  // Uploaded Proof Photos strip (when item has multiple proof photos)
  const proofPhotos = [
    item.front_cover_path || item.image_url,
    item.back_cover_path,
    item.spine_path,
    item.inside_pages_path
  ].filter(Boolean);

  const messages = req.messages || [];

  container.innerHTML = `
    <div class="req-header-bar">
      <div>
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 4px;">
          <span class="mono-code">${escapeHtml(req.request_code)}</span>
          <span class="badge ${getRequestStatusBadgeClass(req.status)}">${escapeHtml(req.status)}</span>
          ${req.is_feed_transaction ? '<span class="badge badge-blue">Student Request Feed Transaction</span>' : ''}
        </div>
        <h2>${escapeHtml(item.title || 'Exchange Transaction')}</h2>
        <p>Requester: <strong>${escapeHtml(requester.name || 'Student')}</strong> &bull; Responder / Owner: <strong>${escapeHtml(owner.name || 'Owner')}</strong></p>
      </div>
    </div>

    <div class="detail-grid">
      <div class="detail-left">
        <div class="requested-item-summary">
          <img src="${escapeHtml(item.image_url || '')}" alt="${escapeHtml(item.title || '')}" />
          <div>
            <span class="badge ${getExchangeBadgeClass(item.exchange_type || 'Lend')}">${escapeHtml(item.exchange_type || 'Lend')}</span>
            <h3>${escapeHtml(item.title || '')}</h3>
            <p>${escapeHtml(item.category || '')} &bull; Condition: ${escapeHtml(item.condition || 'Good')}</p>
          </div>
        </div>

        ${proofPhotos.length > 1 ? `
          <div class="timeline-card">
            <h3>Uploaded Device Proof Photos</h3>
            <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px;">
              ${proofPhotos.map((url, idx) => `
                <a href="${escapeHtml(url)}" target="_blank" rel="noopener" style="display: block; border: 1px solid #E5E7EB; border-radius: 10px; overflow: hidden;">
                  <img src="${escapeHtml(url)}" alt="Proof Photo ${idx + 1}" style="width: 100%; height: 110px; object-fit: cover; display: block;" />
                </a>
              `).join('')}
            </div>
          </div>
        ` : ''}

        <div class="timeline-card">
          <h3>Transaction Lifecycle</h3>
          <div class="timeline-steps">
            <div class="timeline-step ${step1Done ? 'done' : ''}">
              <div class="step-dot">1</div>
              <div>
                <strong>Request Initiated</strong>
                <p>Created on ${escapeHtml(req.created_time || req.created_at)}</p>
              </div>
            </div>
            <div class="timeline-step ${step2Done ? 'done' : ''}">
              <div class="step-dot">2</div>
              <div>
                <strong>Accepted &amp; Pickup Coordination</strong>
                <p>Agree on a campus meetup spot and time in the chat thread.</p>
              </div>
            </div>
            <div class="timeline-step ${step3Done ? 'done' : ''}">
              <div class="step-dot">3</div>
              <div>
                <strong>Physical Handover Complete</strong>
                <p>Both parties confirm the resource handover is complete.</p>
              </div>
            </div>
          </div>

          ${lifecycleButtonsHTML}
        </div>
      </div>

      <div class="detail-right">
        <div class="chat-card">
          <div class="chat-header">
            <h4>Pickup Coordination Chat</h4>
            <span class="badge badge-neutral">${messages.length} Message${messages.length === 1 ? '' : 's'}</span>
          </div>

          <div id="request-chat-messages" class="chat-messages-box">
            ${messages.length === 0 ? `
              <p class="text-muted" style="text-align: center; margin: auto;">No messages yet. Say hello to coordinate pickup!</p>
            ` : messages.map(msg => {
              const isMine = msg.sender_id === currentUser.id;
              return `
                <div class="chat-bubble-row ${isMine ? 'mine' : 'theirs'}">
                  <div class="chat-bubble">
                    <div class="chat-sender">${escapeHtml(msg.sender_name)}</div>
                    <div>${escapeHtml(msg.content)}</div>
                    <span class="chat-time">${escapeHtml(msg.timestamp)}</span>
                  </div>
                </div>
              `;
            }).join('')}
          </div>

          ${(req.status !== 'Cancelled' && req.status !== 'Declined' && req.status !== 'Handover') ? `
            <form class="chat-input-row" onsubmit="handleSendMessage(event, ${req.id})">
              <input
                type="text"
                id="request-chat-input"
                required
                placeholder="Write a message to coordinate pickup details..."
              />
              <button type="submit" class="btn-primary btn-sm">Send</button>
            </form>
          ` : ''}
        </div>
      </div>
    </div>
  `;

  const chatBox = document.getElementById('request-chat-messages');
  if (chatBox) {
    chatBox.scrollTop = chatBox.scrollHeight;
  }
}

async function handleUpdateRequestStatus(reqId, newStatus) {
  try {
    const res = await fetch(`/api/requests/${reqId}/status`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus })
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Could not update request status.');
    }

    showToast(data.message || `Status updated to ${newStatus}.`);
    currentInspectRequest = data.request;
    renderRequestDetails(data.request);
    await loadAllRequests();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function cancelTransactionRequest(reqId) {
  try {
    const res = await fetch(`/api/requests/${reqId}/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to cancel request.');
    }

    // Update client state arrays cleanly
    if (Array.isArray(data.my_requests)) {
      myRequestsList = data.my_requests;
    }
    if (Array.isArray(data.incoming_requests)) {
      incomingRequestsList = data.incoming_requests;
    }

    renderRequestsStack('my-requests-container', myRequestsList, 'outgoing');
    renderRequestsStack('incoming-requests-container', incomingRequestsList, 'incoming');

    if (currentUser && currentUser.role === 'Student') {
      await loadFeedWorkspace();
    }

    showToast(data.message || 'Request cancelled and closed out.');
    // Transition single-page DOM focus smoothly back to core active request deck without reloading
    navigateTo('my-requests');
  } catch (err) {
    showToast(err.message, true);
  }
}

async function handleSendMessage(event, reqId) {
  event.preventDefault();
  const input = document.getElementById('request-chat-input');
  if (!input) return;
  const content = input.value.trim();
  if (!content) return;

  input.value = '';
  try {
    const res = await fetch(`/api/requests/${reqId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content })
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Could not send message.');
    }

    if (data.request) {
      currentInspectRequest = data.request;
      renderRequestDetails(data.request);
    } else {
      await openRequestDetails(reqId);
    }
  } catch (err) {
    showToast(err.message, true);
  }
}

// --------------------------------------------------------------------------
// 10. PROFILE & ACCOUNT SECURITY HANDLERS
// --------------------------------------------------------------------------
function enforceDashboardNepaliPhone(inputEl) {
  let raw = inputEl.value;
  const trimmed = raw.trimStart();
  if (trimmed.startsWith('(+977)')) {
    const afterPrefix = trimmed.slice(6).replace(/\D/g, '').slice(0, 10);
    inputEl.value = afterPrefix.length > 0 ? `(+977) ${afterPrefix}` : '(+977) ';
  } else if (trimmed.startsWith('+977')) {
    const afterPrefix = trimmed.slice(4).replace(/\D/g, '').slice(0, 10);
    inputEl.value = afterPrefix.length > 0 ? `(+977) ${afterPrefix}` : '(+977) ';
  } else {
    inputEl.value = raw.replace(/\D/g, '').slice(0, 10);
  }
}

async function handleUpdateProfile(event) {
  event.preventDefault();
  const name = document.getElementById('prof-name').value.trim();
  const email = document.getElementById('prof-email').value.trim().toLowerCase();
  const phone = document.getElementById('prof-phone').value.trim();
  const university = document.getElementById('prof-university').value.trim();

  if (!NEPALI_PHONE_DASH_REGEX.test(phone)) {
    showToast('Invalid phone number. Enter optional (+977) prefix followed by 10 digits.', true);
    return;
  }

  try {
    const res = await fetch('/api/profile/update', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, phone, university })
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to update profile.');
    }

    currentUser = data.user;
    syncUserHeaderAndComposer();
    showToast(data.message || 'Personal details updated successfully.');
  } catch (err) {
    showToast(err.message, true);
  }
}

async function handleChangePassword(event) {
  event.preventDefault();
  const current_password = document.getElementById('pw-current').value;
  const new_password = document.getElementById('pw-new').value;

  try {
    const res = await fetch('/api/profile/password', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password, new_password })
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Could not update password.');
    }

    document.getElementById('pw-current').value = '';
    document.getElementById('pw-new').value = '';
    showToast(data.message || 'Password updated successfully.');
  } catch (err) {
    showToast(err.message, true);
  }
}

function requestDeleteAccountConfirmation() {
  openConfirmModal(
    'Are you sure you want to permanently delete your ShareLoop account? This action cannot be undone.',
    'Delete Account',
    performDeleteAccount
  );
}

async function performDeleteAccount() {
  try {
    const res = await fetch('/api/profile/delete', { method: 'DELETE' });
    if (res.ok) {
      window.location.href = '/login';
    } else {
      const data = await res.json().catch(() => ({}));
      showToast(data.error || 'Failed to delete account.', true);
    }
  } catch (err) {
    showToast('Network error while deleting account.', true);
  }
}

// --------------------------------------------------------------------------
// 11. ADMIN PORTAL: 5 DEDICATED MODULES & REACTIVE CHARTS
// --------------------------------------------------------------------------
async function loadAdminOverview() {
  const statsGrid = document.getElementById('admin-overview-stats-grid');
  if (!statsGrid) return;

  try {
    const res = await fetch('/api/admin/overview');
    if (!res.ok) return;
    const data = await res.json();
    cachedAdminOverview = data;

    const stats = data.stats || {};
    const charts = data.charts || {};

    // 4 Core KPI Data Channel Cards
    statsGrid.innerHTML = `
      <div class="kpi-card">
        <span class="kpi-label">Total Platform Users</span>
        <strong class="kpi-value">${stats.total_platform_users ?? 0}</strong>
        <span class="kpi-sub">Active Students (${stats.student_count ?? 0}) + Approved Orgs (${stats.organization_count ?? 0})</span>
      </div>
      <div class="kpi-card">
        <span class="kpi-label">Resource Listings</span>
        <strong class="kpi-value">${stats.resource_listings ?? 0}</strong>
        <span class="kpi-sub">${stats.available_items ?? 0} Available &bull; ${stats.unavailable_items ?? 0} Unavailable</span>
      </div>
      <div class="kpi-card">
        <span class="kpi-label">Exchange Transactions</span>
        <strong class="kpi-value">${stats.exchange_transactions ?? 0}</strong>
        <span class="kpi-sub">Completed exchanges (status = Handover)</span>
      </div>
      <div class="kpi-card">
        <span class="kpi-label">Coordination Messages</span>
        <strong class="kpi-value">${stats.coordination_messages ?? 0}</strong>
        <span class="kpi-sub">Messages logged in Accepted requests</span>
      </div>
    `;

    // Populate Month Selector for "Exchanges Over Time"
    const monthSelect = document.getElementById('admin-chart-month-select');
    const timeline = charts.exchanges_over_time || {};
    const monthsList = timeline.months || [];
    if (monthSelect) {
      const prevSelected = monthSelect.value;
      monthSelect.innerHTML = `
        <option value="ALL">All Months</option>
        ${monthsList.map(m => `<option value="${escapeHtml(m.key)}">${escapeHtml(m.label)}</option>`).join('')}
      `;
      if (prevSelected && (prevSelected === 'ALL' || monthsList.some(m => m.key === prevSelected))) {
        monthSelect.value = prevSelected;
      } else if (monthsList.length > 0) {
        monthSelect.value = monthsList[0].key;
      } else {
        monthSelect.value = 'ALL';
      }
      renderAdminLineChart(monthSelect.value);
    }

    renderAdminDoughnutChart(charts.exchange_types_breakdown || { Lend: 0, Donate: 0, Swap: 0 });
    renderAdminTopCategoriesChart(charts.top_categories_shared || []);
  } catch (err) {
    console.error('Error loading admin overview:', err);
  }
}

function handleOverviewMonthChange(monthKey) {
  renderAdminLineChart(monthKey);
}

function renderAdminLineChart(selectedMonthKey) {
  const container = document.getElementById('admin-line-chart-container');
  if (!container || !cachedAdminOverview) return;

  const timeline = (cachedAdminOverview.charts && cachedAdminOverview.charts.exchanges_over_time) || {};
  const weekLabels = timeline.week_labels || ['Week 1', 'Week 2', 'Week 3', 'Week 4'];
  let counts = [0, 0, 0, 0];

  if (!selectedMonthKey || selectedMonthKey === 'ALL') {
    counts = timeline.all_months_weeks || [0, 0, 0, 0];
  } else {
    const foundMonth = (timeline.months || []).find(m => m.key === selectedMonthKey);
    if (foundMonth && Array.isArray(foundMonth.weeks)) {
      counts = foundMonth.weeks;
    }
  }

  const maxVal = Math.max(4, ...counts);
  const width = 520;
  const height = 210;
  const padLeft = 40;
  const padRight = 26;
  const padTop = 24;
  const padBottom = 36;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  const coords = counts.map((val, idx) => {
    const x = padLeft + (counts.length > 1 ? (idx / (counts.length - 1)) * plotW : plotW / 2);
    const y = padTop + plotH - (val / maxVal) * plotH;
    return { x, y, val, label: weekLabels[idx] || `Week ${idx + 1}` };
  });

  const polylinePoints = coords.map(c => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ');
  const areaPoints = `${coords[0].x.toFixed(1)},${(padTop + plotH).toFixed(1)} ${polylinePoints} ${coords[coords.length - 1].x.toFixed(1)},${(padTop + plotH).toFixed(1)}`;

  const yTicks = [0, Math.round(maxVal / 2), maxVal];
  const gridLines = yTicks.map(tick => {
    const y = padTop + plotH - (tick / maxVal) * plotH;
    return `
      <line x1="${padLeft}" y1="${y.toFixed(1)}" x2="${width - padRight}" y2="${y.toFixed(1)}" stroke="#E5E7EB" stroke-dasharray="4 4" stroke-width="1" />
      <text x="${padLeft - 8}" y="${(y + 4).toFixed(1)}" text-anchor="end" fill="#6B7280" font-size="11" font-weight="600">${tick}</text>
    `;
  }).join('');

  const pointsSVG = coords.map(c => `
    <g>
      <circle cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(1)}" r="5.5" fill="#1B3B2B" stroke="#FFFFFF" stroke-width="2" />
      <text x="${c.x.toFixed(1)}" y="${(c.y - 10).toFixed(1)}" text-anchor="middle" fill="#111827" font-size="11" font-weight="700">${c.val}</text>
      <text x="${c.x.toFixed(1)}" y="${height - 10}" text-anchor="middle" fill="#4B5563" font-size="11" font-weight="600">${escapeHtml(c.label)}</text>
    </g>
  `).join('');

  const totalHandovers = counts.reduce((a, b) => a + b, 0);

  container.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" class="admin-line-svg" role="img" aria-label="Exchanges Over Time">
      <defs>
        <linearGradient id="lineAreaFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#1B3B2B" stop-opacity="0.24" />
          <stop offset="100%" stop-color="#1B3B2B" stop-opacity="0.02" />
        </linearGradient>
      </defs>
      ${gridLines}
      <polygon points="${areaPoints}" fill="url(#lineAreaFill)" />
      <polyline fill="none" stroke="#1B3B2B" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" points="${polylinePoints}" />
      ${pointsSVG}
    </svg>
    <div class="admin-chart-footer-meta">
      Completed Handovers in Period: <strong>${totalHandovers}</strong>
    </div>
  `;
}

function renderAdminDoughnutChart(breakdown) {
  const container = document.getElementById('admin-doughnut-chart-container');
  if (!container) return;

  const lend = Number(breakdown.Lend || 0);
  const donate = Number(breakdown.Donate || 0);
  const swap = Number(breakdown.Swap || 0);
  const total = lend + donate + swap;

  const slices = [
    { label: 'Lend', count: lend, color: '#2563EB' },
    { label: 'Donate', count: donate, color: '#16A34A' },
    { label: 'Swap', count: swap, color: '#D97706' }
  ];

  const radius = 60;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  const circles = total > 0
    ? slices.map(s => {
        if (s.count <= 0) return '';
        const dash = (s.count / total) * circumference;
        const gap = circumference - dash;
        const currentOffset = -offset;
        offset += dash;
        return `
          <circle
            cx="85"
            cy="85"
            r="${radius}"
            fill="transparent"
            stroke="${s.color}"
            stroke-width="24"
            stroke-dasharray="${dash.toFixed(2)} ${gap.toFixed(2)}"
            stroke-dashoffset="${currentOffset.toFixed(2)}"
            transform="rotate(-90 85 85)"
          />
        `;
      }).join('')
    : `<circle cx="85" cy="85" r="${radius}" fill="transparent" stroke="#E5E7EB" stroke-width="24" />`;

  container.innerHTML = `
    <div class="doughnut-layout">
      <div class="doughnut-svg-wrap">
        <svg width="170" height="170" viewBox="0 0 170 170" role="img" aria-label="Exchange Types Breakdown">
          ${circles}
          <text x="85" y="81" text-anchor="middle" fill="#111827" font-size="22" font-weight="800">${total}</text>
          <text x="85" y="99" text-anchor="middle" fill="#6B7280" font-size="11" font-weight="600">Active Items</text>
        </svg>
      </div>
      <div class="doughnut-legend">
        ${slices.map(s => {
          const pct = total > 0 ? Math.round((s.count / total) * 100) : 0;
          return `
            <div class="doughnut-legend-item">
              <span class="doughnut-legend-swatch" style="background: ${s.color};"></span>
              <div class="doughnut-legend-text">
                <span class="doughnut-legend-label">${escapeHtml(s.label)}</span>
                <span class="doughnut-legend-val"><strong>${s.count}</strong> (${pct}%)</span>
              </div>
            </div>
          `;
        }).join('')}
      </div>
    </div>
  `;
}

function renderAdminTopCategoriesChart(categories) {
  const container = document.getElementById('admin-top-categories-container');
  if (!container) return;

  if (!categories || categories.length === 0) {
    container.innerHTML = `<div class="empty-state"><p>No active resource listings to categorize.</p></div>`;
    return;
  }

  const maxCount = Math.max(1, ...categories.map(c => c.count || 0));
  container.innerHTML = categories.map(cat => {
    const widthPct = Math.max(6, Math.round(((cat.count || 0) / maxCount) * 100));
    return `
      <div class="category-bar-row">
        <div class="category-bar-header">
          <span class="category-bar-name">${escapeHtml(cat.category)}</span>
          <span class="category-bar-stats"><strong>${cat.count}</strong> listing${cat.count === 1 ? '' : 's'} (${cat.percentage ?? 0}%)</span>
        </div>
        <div class="category-bar-track">
          <div class="category-bar-fill" style="width: ${widthPct}%;"></div>
        </div>
      </div>
    `;
  }).join('');
}

// --- Admin View 2: Resource Feed Moderation ---
function filterAdminSidebarCategoryList(query) {
  const scrollbox = document.getElementById('admin-filter-category-scrollbox');
  if (!scrollbox) return;
  const q = (query || '').trim().toLowerCase();

  scrollbox.querySelectorAll('.category-filter-group').forEach(group => {
    let visibleCount = 0;
    group.querySelectorAll('.category-filter-item').forEach(item => {
      const label = (item.dataset.label || item.textContent || '').toLowerCase();
      if (!q || label.includes(q)) {
        item.style.display = 'flex';
        visibleCount++;
      } else {
        item.style.display = 'none';
      }
    });
    group.style.display = visibleCount > 0 ? 'block' : 'none';
  });
}

function resetAdminResourceFilters() {
  document.querySelectorAll('.admin-filter-exchange, .admin-filter-category, .admin-filter-condition').forEach(cb => {
    cb.checked = false;
  });
  const availOnly = document.getElementById('admin-filter-available-only');
  if (availOnly) availOnly.checked = false;

  const searchInput = document.getElementById('admin-filter-category-search');
  if (searchInput) {
    searchInput.value = '';
    filterAdminSidebarCategoryList('');
  }
  const globalSearch = document.getElementById('global-search-input');
  if (globalSearch) globalSearch.value = '';

  loadAdminResources();
}

async function loadAdminResources() {
  const container = document.getElementById('admin-resources-container');
  if (!container) return;

  const search = (document.getElementById('global-search-input')?.value || '').trim();
  const exchanges = Array.from(document.querySelectorAll('.admin-filter-exchange:checked')).map(el => el.value);
  const categories = Array.from(document.querySelectorAll('.admin-filter-category:checked')).map(el => el.value);
  const conditions = Array.from(document.querySelectorAll('.admin-filter-condition:checked')).map(el => el.value);
  const availableOnly = document.getElementById('admin-filter-available-only')?.checked ?? false;

  const params = new URLSearchParams();
  if (search) params.set('search', search);
  if (exchanges.length) params.set('exchange_types', exchanges.join(','));
  if (categories.length) params.set('categories', categories.join('||'));
  if (conditions.length) params.set('conditions', conditions.join(','));
  if (availableOnly) params.set('available_only', 'true');

  try {
    const res = await fetch(`/api/admin/resources?${params.toString()}`);
    if (!res.ok) return;
    const data = await res.json();
    const resources = data.resources || data.items || [];

    if (resources.length === 0) {
      container.innerHTML = `<div class="empty-state"><h3>No matching listings</h3><p>Try clearing some filters in the right panel.</p></div>`;
      return;
    }

    // Strictly two action buttons: "Inspect" and "Delete" (No "Mark Available" button)
    container.innerHTML = resources.map(item => {
      const owner = item.owner || {};
      return `
        <div class="list-row-card">
          <img src="${escapeHtml(item.image_url)}" alt="${escapeHtml(item.title)}" class="list-row-thumb" />
          <div class="list-row-info">
            <div class="list-row-tags">
              <span class="course-tag">${escapeHtml(item.course_code || 'GEN 101')}</span>
              <span class="badge ${getExchangeBadgeClass(item.exchange_type)}">${escapeHtml(item.exchange_type)}</span>
              <span class="badge badge-neutral">${escapeHtml(item.condition)}</span>
              <span class="status-pill ${item.is_available ? 'available' : 'unavailable'}">
                ${item.is_available ? '● Available' : '○ Unavailable'}
              </span>
            </div>
            <h3>${escapeHtml(item.title)}</h3>
            <p>${escapeHtml(item.category)} &bull; Owner: <strong>${escapeHtml(owner.name || 'Student')}</strong> (${escapeHtml(owner.role || 'Student')})</p>
          </div>
          <div class="list-row-actions">
            <button type="button" class="btn-outline btn-sm" onclick="openItemDetails(${item.id}, 'admin-resources')">Inspect</button>
            <button type="button" class="btn-danger btn-sm" onclick="confirmDeleteItem(${item.id})">Delete</button>
          </div>
        </div>
      `;
    }).join('');
  } catch (err) {
    console.error('Error loading admin resources:', err);
  }
}

// --- Admin View 3: Transactions & Status Filter Tags ---
function selectAdminTransactionStatusFilter(status) {
  selectedAdminTxStatus = status || 'All';
  document.querySelectorAll('#admin-tx-status-filters .status-filter-tag').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.status === selectedAdminTxStatus);
  });
  loadAdminTransactions();
}

async function loadAdminTransactions() {
  const container = document.getElementById('admin-transactions-container');
  if (!container) return;

  const params = new URLSearchParams();
  if (selectedAdminTxStatus && selectedAdminTxStatus !== 'All') {
    params.set('status', selectedAdminTxStatus);
  }

  try {
    const res = await fetch(`/api/admin/transactions?${params.toString()}`);
    if (!res.ok) return;
    const data = await res.json();
    const txs = data.transactions || data.requests || [];

    if (txs.length === 0) {
      container.innerHTML = `<div class="empty-state"><h3>No matching transactions</h3><p>No exchange requests match the "${escapeHtml(selectedAdminTxStatus)}" status filter.</p></div>`;
      return;
    }

    container.innerHTML = txs.map(req => {
      const item = req.item || {};
      const requester = req.requester || {};
      const owner = req.owner || {};
      return `
        <div class="list-row-card">
          <img src="${escapeHtml(item.image_url || '')}" alt="${escapeHtml(item.title || '')}" class="list-row-thumb" />
          <div class="list-row-info">
            <div class="list-row-tags">
              <span class="mono-code">${escapeHtml(req.request_code)}</span>
              <span class="badge ${getExchangeBadgeClass(item.exchange_type || 'Lend')}">${escapeHtml(item.exchange_type || 'Lend')}</span>
              <span class="badge ${getRequestStatusBadgeClass(req.status)}">${escapeHtml(req.status)}</span>
            </div>
            <h3>${escapeHtml(item.title || 'Resource Transaction')}</h3>
            <p>Requester: <strong>${escapeHtml(requester.name || 'Student')}</strong> &rarr; Owner: <strong>${escapeHtml(owner.name || 'Owner')}</strong> &bull; ${escapeHtml(req.created_at)}</p>
          </div>
        </div>
      `;
    }).join('');
  } catch (err) {
    console.error('Error loading admin transactions:', err);
  }
}

// --- Admin View 4: Registered / Active Accounts (Instantaneous Client-Side Role Toggle: Student vs Organization) ---
function selectAdminActiveAccountRoleFilter(role) {
  selectedActiveAccountRoleFilter = role === 'Organization' ? 'Organization' : 'Student';
  document.querySelectorAll('#admin-active-role-toggle .status-filter-tag').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.role === selectedActiveAccountRoleFilter);
  });
  renderAdminActiveAccountsList();
}

function renderAdminActiveAccountsList() {
  const container = document.getElementById('admin-active-accounts-list');
  if (!container) return;

  const filteredAccounts = (cachedAdminActiveAccounts || []).filter(acc => {
    if (selectedActiveAccountRoleFilter === 'Organization') {
      return acc.role === 'Organization' && acc.is_approved !== false;
    }
    return acc.role === 'Student';
  });

  if (filteredAccounts.length === 0) {
    const roleLabel = selectedActiveAccountRoleFilter === 'Organization' ? 'verified organization' : 'registered student';
    container.innerHTML = `<div class="empty-state"><h3>No ${escapeHtml(roleLabel)} accounts found</h3></div>`;
    return;
  }

  container.innerHTML = filteredAccounts.map(acc => `
    <div class="list-row-card">
      <div class="avatar-circle lg">${escapeHtml(acc.initials || 'U')}</div>
      <div class="list-row-info">
        <div class="list-row-tags">
          <span class="badge ${acc.role === 'Organization' ? 'badge-amber' : 'badge-green'}">${escapeHtml(acc.role)}</span>
          <span class="status-pill available">● Active</span>
        </div>
        <h3>${escapeHtml(acc.name)}</h3>
        <p>${escapeHtml(acc.email)} ${acc.phone ? '&bull; ' + escapeHtml(acc.phone) : ''} ${acc.dob ? '&bull; DOB: ' + escapeHtml(acc.dob) : ''}</p>
      </div>
      <div class="list-row-actions">
        <span class="text-muted">Joined ${escapeHtml(acc.created_at)}</span>
      </div>
    </div>
  `).join('');
}

async function loadAdminActiveAccounts() {
  const container = document.getElementById('admin-active-accounts-list');
  if (!container) return;

  try {
    const res = await fetch('/api/admin/accounts/active');
    if (!res.ok) return;
    const data = await res.json();
    cachedAdminActiveAccounts = data.accounts || data.users || [];

    // Ensure toggle button active state matches selectedActiveAccountRoleFilter
    document.querySelectorAll('#admin-active-role-toggle .status-filter-tag').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.role === selectedActiveAccountRoleFilter);
    });

    renderAdminActiveAccountsList();
  } catch (err) {
    console.error('Error loading active accounts:', err);
  }
}

// --- Admin View 5: Pending Organization Approvals ("Approve Account" Green & "Cancel Request" Red) ---
async function loadAdminPendingAccountsBadgeOnly() {
  try {
    const res = await fetch('/api/admin/accounts/pending');
    if (!res.ok) return;
    const data = await res.json();
    const pending = data.accounts || data.users || [];
    updateSidebarPendingBadge(pending.length);
  } catch (err) {
    // ignore
  }
}

function updateSidebarPendingBadge(count) {
  const badge = document.getElementById('sidebar-pending-badge');
  if (!badge) return;
  if (count > 0) {
    badge.textContent = count;
    badge.classList.remove('hidden');
  } else {
    badge.classList.add('hidden');
  }
}

async function loadAdminPendingAccounts() {
  const container = document.getElementById('admin-pending-accounts-list');
  if (!container) return;

  try {
    const res = await fetch('/api/admin/accounts/pending');
    if (!res.ok) return;
    const data = await res.json();
    const pending = data.accounts || data.users || [];

    updateSidebarPendingBadge(pending.length);

    if (pending.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <h3>No Pending Organization Registrations</h3>
          <p>All incoming organization registration requests have been reviewed.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = pending.map(org => `
      <div class="list-row-card">
        <div class="avatar-circle lg">${escapeHtml(org.initials || 'OR')}</div>
        <div class="list-row-info">
          <div class="list-row-tags">
            <span class="badge badge-amber">Organization</span>
            <span class="badge badge-neutral">Domain: @${escapeHtml(org.email_domain)}</span>
            <span class="badge badge-amber">Status: Pending Verification</span>
          </div>
          <h3>${escapeHtml(org.name)}</h3>
          <p>${escapeHtml(org.email)} ${org.phone ? '&bull; ' + escapeHtml(org.phone) : ''} &bull; Registered ${escapeHtml(org.registered_at || org.created_at)}</p>
        </div>
        <div class="list-row-actions">
          <button type="button" class="btn-approve-green btn-sm" onclick="handleOrganizationApprovalDecision(${org.id}, 'Approve')">
            Approve Account
          </button>
          <button type="button" class="btn-danger btn-sm" onclick="handleOrganizationApprovalDecision(${org.id}, 'Reject')">
            Cancel Request
          </button>
        </div>
      </div>
    `).join('');
  } catch (err) {
    console.error('Error loading pending organization accounts:', err);
  }
}

async function handleOrganizationApprovalDecision(userId, decision) {
  try {
    const res = await fetch(`/api/admin/accounts/decision/${userId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision })
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Could not process decision.');
    }

    showToast(data.message || 'Organization account updated.');
    await loadAdminPendingAccounts();
    await loadAdminActiveAccounts();
    await loadAdminOverview();
  } catch (err) {
    showToast(err.message, true);
  }
}

// --------------------------------------------------------------------------
// 12. ESCAPING UTILITIES
// --------------------------------------------------------------------------
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function escapeAttr(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'")
    .replace(/"/g, '&quot;');
}
