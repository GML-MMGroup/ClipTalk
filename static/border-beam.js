(function(){var e,t,n,r,i,a,o,s,c,l,u,d,f,p,m={},h=[],g=/acit|ex(?:s|g|n|p|$)|rph|grid|ows|mnc|ntw|ine[ch]|zoo|^ord|itera/i,_=Array.isArray;function v(e,t){for(var n in t)e[n]=t[n];return e}function y(e){e&&e.parentNode&&e.parentNode.removeChild(e)}function b(t,n,r){var i,a,o,s={};for(o in n)o==`key`?i=n[o]:o==`ref`?a=n[o]:s[o]=n[o];if(arguments.length>2&&(s.children=arguments.length>3?e.call(arguments,2):r),typeof t==`function`&&t.defaultProps!=null)for(o in t.defaultProps)s[o]===void 0&&(s[o]=t.defaultProps[o]);return x(t,s,i,a,null)}function x(e,r,i,a,o){var s={type:e,props:r,key:i,ref:a,__k:null,__:null,__b:0,__e:null,__c:null,constructor:void 0,__v:o??++n,__i:-1,__u:0};return o==null&&t.vnode!=null&&t.vnode(s),s}function S(e){return e.children}function C(e,t){this.props=e,this.context=t}function w(e,t){if(t==null)return e.__?w(e.__,e.__i+1):null;for(var n;t<e.__k.length;t++)if((n=e.__k[t])!=null&&n.__e!=null)return n.__e;return typeof e.type==`function`?w(e):null}function T(e){if(e.__P&&e.__d){var n=e.__v,r=n.__e,i=[],a=[],o=v({},n);o.__v=n.__v+1,t.vnode&&t.vnode(o),I(e.__P,o,n,e.__n,e.__P.namespaceURI,32&n.__u?[r]:null,i,r??w(n),!!(32&n.__u),a),o.__v=n.__v,o.__.__k[o.__i]=o,L(i,o,a),n.__e=n.__=null,o.__e!=r&&E(o)}}function E(e){if((e=e.__)!=null&&e.__c!=null)return e.__e=e.__c.base=null,e.__k.some(function(t){if(t!=null&&t.__e!=null)return e.__e=e.__c.base=t.__e}),E(e)}function D(e){(!e.__d&&(e.__d=!0)&&r.push(e)&&!O.__r++||i!=t.debounceRendering)&&((i=t.debounceRendering)||a)(O)}function O(){try{for(var e,t=1;r.length;)r.length>t&&r.sort(o),e=r.shift(),t=r.length,T(e)}finally{r.length=O.__r=0}}function ee(e,t,n,r,i,a,o,s,c,l,u){var d,f,p,g,_,v,y=r&&r.__k||h,b=t.length;for(c=k(n,t,y,c,b),d=0;d<b;d++)(p=n.__k[d])!=null&&(f=p.__i!=-1&&y[p.__i]||m,p.__i=d,v=I(e,p,f,i,a,o,s,c,l,u),g=p.__e,p.ref&&f.ref!=p.ref&&(f.ref&&R(f.ref,null,p),u.push(p.ref,p.__c||g,p)),_==null&&g!=null&&(_=g),4&p.__u?(c=A(p,c,e),f.__e&&(f.__e=null)):typeof p.type==`function`&&v!==void 0?c=v:g&&(c=g.nextSibling),p.__u&=-7);return n.__e=_,c}function k(e,t,n,r,i){var a,o,s,c,l,u=n.length,d=u,f=0;for(e.__k=Array(i),a=0;a<i;a++)(o=t[a])!=null&&typeof o!=`boolean`&&typeof o!=`function`?(typeof o==`string`||typeof o==`number`||typeof o==`bigint`||o.constructor==String?o=e.__k[a]=x(null,o,null,null,null):_(o)?o=e.__k[a]=x(S,{children:o},null,null,null):o.constructor===void 0&&o.__b>0?o=e.__k[a]=x(o.type,o.props,o.key,o.ref?o.ref:null,o.__v):e.__k[a]=o,c=a+f,o.__=e,o.__b=e.__b+1,s=null,(l=o.__i=M(o,n,c,d))!=-1&&(d--,(s=n[l])&&(s.__u|=2)),s==null||s.__v==null?(l==-1&&(i>u?f--:i<u&&f++),typeof o.type!=`function`&&(o.__u|=4)):l!=c&&(l==c-1?f--:l==c+1?f++:(l>c?f--:f++,o.__u|=4))):e.__k[a]=null;if(d)for(a=0;a<u;a++)(s=n[a])!=null&&!(2&s.__u)&&(s.__e==r&&(r=w(s)),z(s,s));return r}function A(e,t,n){var r,i;if(typeof e.type==`function`){for(r=e.__k,i=0;r&&i<r.length;i++)r[i]&&(r[i].__=e,t=A(r[i],t,n));return t}e.__e!=t&&(t&&e.type&&!t.parentNode&&(t=w(e)),t=n.insertBefore(e.__e,t||null));do t&&=t.nextSibling;while(t!=null&&t.nodeType==8);return t}function j(e,t){return t||=[],e==null||typeof e==`boolean`||(_(e)?e.some(function(e){j(e,t)}):t.push(e)),t}function M(e,t,n,r){var i,a,o,s=e.key,c=e.type,l=t[n],u=l!=null&&!(2&l.__u);if(l===null&&s==null||u&&s==l.key&&c==l.type)return n;if(r>+!!u){for(i=n-1,a=n+1;i>=0||a<t.length;)if((l=t[o=i>=0?i--:a++])!=null&&!(2&l.__u)&&s==l.key&&c==l.type)return o}return-1}function N(e,t,n){t[0]==`-`?e.setProperty(t,n??``):e[t]=n==null?``:typeof n!=`number`||g.test(t)?n:n+`px`}function P(e,t,n,r,i){var a,o;n:if(t==`style`)if(typeof n==`string`)e.style.cssText=n;else{if(typeof r==`string`&&(e.style.cssText=r=``),r)for(t in r)n&&t in n||N(e.style,t,``);if(n)for(t in n)r&&n[t]==r[t]||N(e.style,t,n[t])}else if(t[0]==`o`&&t[1]==`n`)a=t!=(t=t.replace(u,`$1`)),o=t.toLowerCase(),t=o in e||t==`onFocusOut`||t==`onFocusIn`?o.slice(2):t.slice(2),e.l||={},e.l[t+a]=n,n?r?n[l]=r[l]:(n[l]=d,e.addEventListener(t,a?p:f,a)):e.removeEventListener(t,a?p:f,a);else{if(i==`http://www.w3.org/2000/svg`)t=t.replace(/xlink(H|:h)/,`h`).replace(/sName$/,`s`);else if(t!=`width`&&t!=`height`&&t!=`href`&&t!=`list`&&t!=`form`&&t!=`tabIndex`&&t!=`download`&&t!=`rowSpan`&&t!=`colSpan`&&t!=`role`&&t!=`popover`&&t in e)try{e[t]=n??``;break n}catch{}typeof n==`function`||(n==null||!1===n&&t[4]!=`-`?e.removeAttribute(t):e.setAttribute(t,t==`popover`&&n==1?``:n))}}function F(e){return function(n){if(this.l){var r=this.l[n.type+e];if(n[c]==null)n[c]=d++;else if(n[c]<r[l])return;return r(t.event?t.event(n):n)}}}function I(e,n,r,i,a,o,s,c,l,u){var d,f,p,m,g,b,x,T,E,D,O,k,A,j,M,N,P=n.type;if(n.constructor!==void 0)return null;128&r.__u&&(l=!!(32&r.__u),o=[c=n.__e=r.__e]),(d=t.__b)&&d(n);n:if(typeof P==`function`){f=s.length;try{if(E=n.props,D=P.prototype&&P.prototype.render,O=(d=P.contextType)&&i[d.__c],k=d?O?O.props.value:d.__:i,r.__c?T=(p=n.__c=r.__c).__=p.__E:(D?n.__c=p=new P(E,k):(n.__c=p=new C(E,k),p.constructor=P,p.render=ie),O&&O.sub(p),p.state||(p.state={}),p.__n=i,m=p.__d=!0,p.__h=[],p._sb=[]),D&&p.__s==null&&(p.__s=p.state),D&&P.getDerivedStateFromProps!=null&&(p.__s==p.state&&(p.__s=v({},p.__s)),v(p.__s,P.getDerivedStateFromProps(E,p.__s))),g=p.props,b=p.state,p.__v=n,m)D&&P.getDerivedStateFromProps==null&&p.componentWillMount!=null&&p.componentWillMount(),D&&p.componentDidMount!=null&&p.__h.push(p.componentDidMount);else{if(D&&P.getDerivedStateFromProps==null&&E!==g&&p.componentWillReceiveProps!=null&&p.componentWillReceiveProps(E,k),n.__v==r.__v||!p.__e&&p.shouldComponentUpdate!=null&&!1===p.shouldComponentUpdate(E,p.__s,k)){n.__v!=r.__v&&(p.props=E,p.state=p.__s,p.__d=!1),n.__e=r.__e,n.__k=r.__k,n.__k.some(function(e){e&&(e.__=n)}),h.push.apply(p.__h,p._sb),p._sb=[],p.__h.length&&s.push(p),c=w(r);break n}p.componentWillUpdate!=null&&p.componentWillUpdate(E,p.__s,k),D&&p.componentDidUpdate!=null&&p.__h.push(function(){p.componentDidUpdate(g,b,x)})}if(p.context=k,p.props=E,p.__P=e,p.__e=!1,A=t.__r,j=0,D)p.state=p.__s,p.__d=!1,A&&A(n),d=p.render(p.props,p.state,p.context),h.push.apply(p.__h,p._sb),p._sb=[];else do p.__d=!1,A&&A(n),d=p.render(p.props,p.state,p.context),p.state=p.__s;while(p.__d&&++j<25);p.state=p.__s,p.getChildContext!=null&&(i=v(v({},i),p.getChildContext())),D&&!m&&p.getSnapshotBeforeUpdate!=null&&(x=p.getSnapshotBeforeUpdate(g,b)),M=d!=null&&d.type===S&&d.key==null?ne(d.props.children):d,c=ee(e,_(M)?M:[M],n,r,i,a,o,s,c,l,u),p.base=n.__e,n.__u&=-161,p.__h.length&&s.push(p),T&&(p.__E=p.__=null)}catch(e){if(s.length=f,n.__v=null,l||o!=null){if(e.then){for(n.__u|=l?160:128;c&&c.nodeType==8&&c.nextSibling;)c=c.nextSibling;o!=null&&(o[o.indexOf(c)]=null),n.__e=c}else if(o!=null)for(N=o.length;N--;)y(o[N])}else n.__e=r.__e;n.__k??=r.__k||[],e.then||te(n),t.__e(e,n,r)}}else o==null&&n.__v==r.__v?(n.__k=r.__k,n.__e=r.__e):c=n.__e=re(r.__e,n,r,i,a,o,s,l,u);return(d=t.diffed)&&d(n),128&n.__u?void 0:c}function te(e){e&&(e.__c&&(e.__c.__e=!0),e.__k&&e.__k.some(te))}function L(e,n,r){for(var i=0;i<r.length;i++)R(r[i],r[++i],r[++i]);t.__c&&t.__c(n,e),e.some(function(n){try{e=n.__h,n.__h=[],e.some(function(e){e.call(n)})}catch(e){t.__e(e,n.__v)}})}function ne(e){return typeof e!=`object`||!e||e.__b>0?e:_(e)?e.map(ne):e.constructor===void 0?v({},e):null}function re(n,r,i,a,o,s,c,l,u){var d,f,p,h,g,v,b,x=i.props||m,S=r.props,C=r.type;if(C==`svg`?o=`http://www.w3.org/2000/svg`:C==`math`?o=`http://www.w3.org/1998/Math/MathML`:o||=`http://www.w3.org/1999/xhtml`,s!=null){for(d=0;d<s.length;d++)if((g=s[d])&&`setAttribute`in g==!!C&&(C?g.localName==C:g.nodeType==3)){n=g,s[d]=null;break}}if(n==null){if(C==null)return document.createTextNode(S);n=document.createElementNS(o,C,S.is&&S),l&&=(t.__m&&t.__m(r,s),!1),s=null}if(C==null)x===S||l&&n.data==S||(n.data=S);else{if(s=C==`textarea`&&S.defaultValue!=null?null:s&&e.call(n.childNodes),!l&&s!=null)for(x={},d=0;d<n.attributes.length;d++)x[(g=n.attributes[d]).name]=g.value;for(d in x)g=x[d],d==`dangerouslySetInnerHTML`?p=g:d==`children`||d in S||d==`value`&&`defaultValue`in S||d==`checked`&&`defaultChecked`in S||P(n,d,null,g,o);for(d in S)g=S[d],d==`children`?h=g:d==`dangerouslySetInnerHTML`?f=g:d==`value`?v=g:d==`checked`?b=g:l&&typeof g!=`function`||x[d]===g||P(n,d,g,x[d],o);if(f)l||p&&(f.__html==p.__html||f.__html==n.innerHTML)||(n.innerHTML=f.__html),r.__k=[];else if(p&&(n.innerHTML=``),ee(r.type==`template`?n.content:n,_(h)?h:[h],r,i,a,C==`foreignObject`?`http://www.w3.org/1999/xhtml`:o,s,c,s?s[0]:i.__k&&w(i,0),l,u),s!=null)for(d=s.length;d--;)y(s[d]);l&&C!=`textarea`||(d=`value`,C==`progress`&&v==null?n.removeAttribute(`value`):v!=null&&(v!==n[d]||C==`progress`&&!v||C==`option`&&v!=x[d])&&P(n,d,v,x[d],o),d=`checked`,b!=null&&b!=n[d]&&P(n,d,b,x[d],o))}return n}function R(e,n,r){try{if(typeof e==`function`){var i=typeof e.__u==`function`;i&&e.__u(),i&&n==null||(e.__u=e(n))}else e.current=n}catch(e){t.__e(e,r)}}function z(e,n,r){var i,a;if(t.unmount&&t.unmount(e),(i=e.ref)&&(i.current&&i.current!=e.__e||R(i,null,n)),(i=e.__c)!=null){if(i.componentWillUnmount)try{i.componentWillUnmount()}catch(e){t.__e(e,n)}i.base=i.__P=i.__n=null}if(i=e.__k)for(a=0;a<i.length;a++)i[a]&&z(i[a],n,r||typeof e.type!=`function`);r||y(e.__e),e.__c=e.__=e.__e=void 0}function ie(e,t,n){return this.constructor(e,n)}function B(n,r,i){var a,o,s,c;r==document&&(r=document.documentElement),t.__&&t.__(n,r),o=(a=typeof i==`function`)?null:i&&i.__k||r.__k,s=[],c=[],I(r,n=(!a&&i||r).__k=b(S,null,[n]),o||m,m,r.namespaceURI,!a&&i?[i]:o?null:r.firstChild?e.call(r.childNodes):null,s,!a&&i?i:o?o.__e:r.firstChild,a,c),L(s,n,c),n.props.children=null}e=h.slice,t={__e:function(e,t,n,r){for(var i,a,o;t=t.__;)if((i=t.__c)&&!i.__)try{if((a=i.constructor)&&a.getDerivedStateFromError!=null&&(i.setState(a.getDerivedStateFromError(e)),o=i.__d),i.componentDidCatch!=null&&(i.componentDidCatch(e,r||{}),o=i.__d),o)return i.__E=i}catch(t){e=t}throw e}},n=0,C.prototype.setState=function(e,t){var n=this.__s!=null&&this.__s!=this.state?this.__s:this.__s=v({},this.state);typeof e==`function`&&(e=e(v({},n),this.props)),e&&v(n,e),e!=null&&this.__v&&(t&&this._sb.push(t),D(this))},C.prototype.forceUpdate=function(e){this.__v&&(this.__e=!0,e&&this.__h.push(e),D(this))},C.prototype.render=S,r=[],a=typeof Promise==`function`?Promise.prototype.then.bind(Promise.resolve()):setTimeout,o=function(e,t){return e.__v.__b-t.__v.__b},O.__r=0,s=Math.random().toString(8),c=`__d`+s,l=`__a`+s,u=/(PointerCapture)$|Capture$/i,d=0,f=F(!1),p=F(!0);var V,H,ae,oe,U=0,se=[],W=t,ce=W.__b,le=W.__r,ue=W.diffed,de=W.__c,fe=W.unmount,pe=W.__;function me(e,t){W.__h&&W.__h(H,e,U||t),U=0;var n=H.__H||(H.__H={__:[],__h:[]});return e>=n.__.length&&n.__.push({}),n.__[e]}function G(e){return U=1,he(Ee,e)}function he(e,t,n){var r=me(V++,2);if(r.t=e,!r.__c&&(r.__=[n?n(t):Ee(void 0,t),function(e){var t=r.__N?r.__N[0]:r.__[0],n=r.t(t,e);t!==n&&(r.__N=[n,r.__[1]],r.__c.setState({}))}],r.__c=H,!H.__f)){var i=function(e,t,n){if(!r.__c.__H)return!0;var i=!1,o=r.__c.props!==e;if(r.__c.__H.__.some(function(e){if(e.__N){i=!0;var t=e.__[0];e.__=e.__N,e.__N=void 0,t!==e.__[0]&&(o=!0)}}),a){var s=a.call(this,e,t,n);return i?s||o:s}return!i||o};H.__f=!0;var a=H.shouldComponentUpdate,o=H.componentWillUpdate;H.componentWillUpdate=function(e,t,n){if(this.__e){var r=a;a=void 0,i(e,t,n),a=r}o&&o.call(this,e,t,n)},H.shouldComponentUpdate=i}return r.__N||r.__}function K(e,t){var n=me(V++,3);!W.__s&&Te(n.__H,t)&&(n.__=e,n.u=t,H.__H.__h.push(n))}function ge(e){return U=5,_e(function(){return{current:e}},[])}function _e(e,t){var n=me(V++,7);return Te(n.__H,t)&&(n.__=e(),n.__H=t,n.__h=e),n.__}function ve(e,t){return U=8,_e(function(){return e},t)}function ye(){var e=me(V++,11);if(!e.__){for(var t=H.__v;t!==null&&!t.__m&&t.__!==null;)t=t.__;var n=t.__m||(t.__m=[0,0]);e.__=`P`+n[0]+`-`+n[1]++}return e.__}function be(){for(var e;e=se.shift();){var t=e.__H;if(e.__P&&t)try{t.__h.some(Ce),t.__h.some(we),t.__h=[]}catch(n){t.__h=[],W.__e(n,e.__v)}}}W.__b=function(e){H=null,ce&&ce(e)},W.__=function(e,t){e&&t.__k&&t.__k.__m&&(e.__m=t.__k.__m),pe&&pe(e,t)},W.__r=function(e){le&&le(e),V=0;var t=(H=e.__c).__H;t&&(ae===H?(t.__h=[],H.__h=[],t.__.some(function(e){e.__N&&(e.__=e.__N),e.u=e.__N=void 0})):(t.__h.some(Ce),t.__h.some(we),t.__h=[],V=0)),ae=H},W.diffed=function(e){ue&&ue(e);var t=e.__c;t&&t.__H&&(t.__H.__h.length&&(se.push(t)!==1&&oe===W.requestAnimationFrame||((oe=W.requestAnimationFrame)||Se)(be)),t.__H.__.some(function(e){e.u&&=(e.__H=e.u,void 0)})),ae=H=null},W.__c=function(e,t){t.some(function(e){try{e.__h.some(Ce),e.__h=e.__h.filter(function(e){return!e.__||we(e)})}catch(n){t.some(function(e){e.__h&&=[]}),t=[],W.__e(n,e.__v)}}),de&&de(e,t)},W.unmount=function(e){fe&&fe(e);var t,n=e.__c;n&&n.__H&&(n.__H.__.some(function(e){try{Ce(e)}catch(e){t=e}}),n.__H=void 0,t&&W.__e(t,n.__v))};var xe=typeof requestAnimationFrame==`function`;function Se(e){var t,n=function(){clearTimeout(r),xe&&cancelAnimationFrame(t),setTimeout(e)},r=setTimeout(n,35);xe&&(t=requestAnimationFrame(n))}function Ce(e){var t=H,n=e.__c;typeof n==`function`&&(e.__c=void 0,n()),H=t}function we(e){var t=H;e.__c=e.__(),H=t}function Te(e,t){return!e||e.length!==t.length||t.some(function(t,n){return t!==e[n]})}function Ee(e,t){return typeof t==`function`?t(e):t}function De(e,t){for(var n in t)e[n]=t[n];return e}function Oe(e,t){for(var n in e)if(n!==`__source`&&!(n in t))return!0;for(var r in t)if(r!==`__source`&&e[r]!==t[r])return!0;return!1}function ke(e,t){this.props=e,this.context=t}(ke.prototype=new C).isPureReactComponent=!0,ke.prototype.shouldComponentUpdate=function(e,t){return Oe(this.props,e)||Oe(this.state,t)};var Ae=t.__b;t.__b=function(e){e.type&&e.type.__f&&e.ref&&(e.props.ref=e.ref,e.ref=null),Ae&&Ae(e)};var je=typeof Symbol<`u`&&Symbol.for&&Symbol.for(`react.forward_ref`)||3911;function Me(e){function t(t){var n=De({},t);return delete n.ref,e(n,t.ref||null)}return t.$$typeof=je,t.render=e,t.prototype.isReactComponent=t.__f=!0,t.displayName=`ForwardRef(`+(e.displayName||e.name)+`)`,t}var Ne=t.__e;t.__e=function(e,t,n,r){if(e.then){for(var i,a=t;a=a.__;)if((i=a.__c)&&i.__c)return t.__e??(t.__e=n.__e,t.__k=n.__k||[]),i.__c(e,t)}Ne(e,t,n,r)};var Pe=t.unmount;function Fe(e,t,n){return e&&(e.__c&&e.__c.__H&&(e.__c.__H.__.forEach(function(e){typeof e.__c==`function`&&e.__c()}),e.__c.__H=null),(e=De({},e)).__c!=null&&(e.__c.__P===n&&(e.__c.__P=t),e.__c.__e=!0,e.__c=null),e.__k=e.__k&&e.__k.map(function(e){return Fe(e,t,n)})),e}function Ie(e,t,n){return e&&n&&(e.__v=null,e.__k=e.__k&&e.__k.map(function(e){return Ie(e,t,n)}),e.__c&&e.__c.__P===t&&(e.__e&&n.appendChild(e.__e),e.__c.__e=!0,e.__c.__P=n)),e}function Le(){this.__u=0,this.o=null,this.__b=null}function Re(e){var t=e.__&&e.__.__c;return t&&t.__a&&t.__a(e)}function ze(){this.i=null,this.l=null}t.unmount=function(e){var t=e.__c;t&&(t.__z=!0),t&&t.__R&&t.__R(),t&&32&e.__u&&(e.type=null),Pe&&Pe(e)},(Le.prototype=new C).__c=function(e,t){var n=t.__c,r=this;r.o??=[],r.o.push(n);var i=Re(r.__v),a=!1,o=function(){a||r.__z||(a=!0,n.__R=null,i?i(c):c())};n.__R=o;var s=n.__P;n.__P=null;var c=function(){if(!--r.__u){if(r.state.__a){var e=r.state.__a;r.__v.__k[0]=Ie(e,e.__c.__P,e.__c.__O)}var t;for(r.setState({__a:r.__b=null});t=r.o.pop();)t.__P=s,t.forceUpdate()}};r.__u++||32&t.__u||r.setState({__a:r.__b=r.__v.__k[0]}),e.then(o,o)},Le.prototype.componentWillUnmount=function(){this.o=[]},Le.prototype.render=function(e,t){if(this.__b){if(this.__v.__k){var n=document.createElement(`div`),r=this.__v.__k[0].__c;this.__v.__k[0]=Fe(this.__b,n,r.__O=r.__P)}this.__b=null}var i=t.__a&&b(S,null,e.fallback);return i&&(i.__u&=-33),[b(S,null,t.__a?null:e.children),i]};var Be=function(e,t,n){if(++n[1]===n[0]&&e.l.delete(t),e.props.revealOrder&&(e.props.revealOrder[0]!==`t`||!e.l.size))for(n=e.i;n;){for(;n.length>3;)n.pop()();if(n[1]<n[0])break;e.i=n=n[2]}};(ze.prototype=new C).__a=function(e){var t=this,n=Re(t.__v),r=t.l.get(e);return r[0]++,function(i){var a=function(){t.props.revealOrder?(r.push(i),Be(t,e,r)):i()};n?n(a):a()}},ze.prototype.render=function(e){this.i=null,this.l=new Map;var t=j(e.children);e.revealOrder&&e.revealOrder[0]===`b`&&t.reverse();for(var n=t.length;n--;)this.l.set(t[n],this.i=[1,0,this.i]);return e.children},ze.prototype.componentDidUpdate=ze.prototype.componentDidMount=function(){var e=this;this.l.forEach(function(t,n){Be(e,n,t)})};var Ve=typeof Symbol<`u`&&Symbol.for&&Symbol.for(`react.element`)||60103,He=/^(?:accent|alignment|arabic|baseline|cap|clip(?!PathU)|color|dominant|fill|flood|font|glyph(?!R)|horiz|image(!S)|letter|lighting|marker(?!H|W|U)|overline|paint|pointer|shape|stop|strikethrough|stroke|text(?!L)|transform|underline|unicode|units|v|vector|vert|word|writing|x(?!C))[A-Z]/,Ue=/^on(Ani|Tra|Tou|BeforeInp|Compo)/,We=/[A-Z0-9]/g,Ge=typeof document<`u`,Ke=function(e){return(typeof Symbol<`u`&&typeof Symbol()==`symbol`?/fil|che|rad/:/fil|che|ra/).test(e)};function qe(e,t,n){return t.__k??(t.textContent=``),B(e,t),typeof n==`function`&&n(),e?e.__c:null}C.prototype.isReactComponent=!0,[`componentWillMount`,`componentWillReceiveProps`,`componentWillUpdate`].forEach(function(e){Object.defineProperty(C.prototype,e,{configurable:!0,get:function(){return this[`UNSAFE_`+e]},set:function(t){Object.defineProperty(this,e,{configurable:!0,writable:!0,value:t})}})});var Je=t.event;t.event=function(e){return Je&&(e=Je(e)),e.persist=function(){},e.isPropagationStopped=function(){return this.cancelBubble},e.isDefaultPrevented=function(){return this.defaultPrevented},e.nativeEvent=e};var Ye={configurable:!0,get:function(){return this.class}},Xe=t.vnode;t.vnode=function(e){typeof e.type==`string`&&function(e){var t=e.props,n=e.type,r={},i=n.indexOf(`-`)==-1;for(var a in t){var o=t[a];if(!(a===`value`&&`defaultValue`in t&&o==null||Ge&&a===`children`&&n===`noscript`||a===`class`||a===`className`)){var s=a.toLowerCase();a===`defaultValue`&&`value`in t&&t.value==null?a=`value`:a===`download`&&!0===o?o=``:s===`translate`&&o===`no`?o=!1:s[0]===`o`&&s[1]===`n`?s===`ondoubleclick`?a=`ondblclick`:s!==`onchange`||n!==`input`&&n!==`textarea`||Ke(t.type)?s===`onfocus`?a=`onfocusin`:s===`onblur`?a=`onfocusout`:Ue.test(a)&&(a=s):s=a=`oninput`:i&&He.test(a)?a=a.replace(We,`-$&`).toLowerCase():o===null&&(o=void 0),s===`oninput`&&r[a=s]&&(a=`oninputCapture`),r[a]=o}}n==`select`&&(r.multiple&&Array.isArray(r.value)&&(r.value=j(t.children).forEach(function(e){e.props.selected=r.value.indexOf(e.props.value)!=-1})),r.defaultValue!=null&&(r.value=j(t.children).forEach(function(e){e.props.selected=r.multiple?r.defaultValue.indexOf(e.props.value)!=-1:r.defaultValue==e.props.value}))),t.class&&!t.className?(r.class=t.class,Object.defineProperty(r,"className",Ye)):t.className&&(r.class=r.className=t.className),e.props=r}(e),e.$$typeof=Ve,Xe&&Xe(e)};var Ze=t.__r;t.__r=function(e){Ze&&Ze(e),e.__c};var Qe=t.diffed;t.diffed=function(e){Qe&&Qe(e);var t=e.props,n=e.__e;n!=null&&e.type===`textarea`&&`value`in t&&t.value!==n.value&&(n.value=t.value==null?``:t.value)};function $e(e){return!!e.__k&&(B(null,e),!0)}function et(e){return{render:function(t){qe(t,e)},unmount:function(){$e(e)}}}var tt=0;Array.isArray;function q(e,n,r,i,a,o){n||={};var s,c,l=n;if(`ref`in l)for(c in l={},n)c==`ref`?s=n[c]:l[c]=n[c];var u={type:e,props:l,key:r,ref:s,__k:null,__:null,__b:0,__e:null,__c:null,constructor:void 0,__v:--tt,__i:-1,__u:0,__source:a,__self:o};if(typeof e==`function`&&(s=e.defaultProps))for(c in s)l[c]===void 0&&(l[c]=s[c]);return t.vnode&&t.vnode(u),u}var nt={sm:{borderRadius:32,borderWidth:1,width:70,height:36},md:{borderRadius:16,borderWidth:1},line:{borderRadius:16,borderWidth:1},"pulse-outside":{borderRadius:16,borderWidth:1},"pulse-inner":{borderRadius:16,borderWidth:1}},rt={sm:{dark:{strokeOpacity:.46,innerOpacity:.24,bloomOpacity:.38,innerShadow:`rgba(255, 255, 255, 0.3)`,saturation:1.2},light:{strokeOpacity:.12,innerOpacity:.3,bloomOpacity:.16,innerShadow:`rgba(0, 0, 0, 0.14)`,saturation:1.8}},md:{dark:{strokeOpacity:.26,innerOpacity:.42,bloomOpacity:.24,innerShadow:`rgba(255, 255, 255, 0.27)`,saturation:1.2},light:{strokeOpacity:.12,innerOpacity:.26,bloomOpacity:.34,innerShadow:`rgba(0, 0, 0, 0.14)`,saturation:1.5}},line:{dark:{strokeOpacity:1.14,innerOpacity:.7,bloomOpacity:.8,innerShadow:`rgba(255, 255, 255, 0.1)`,saturation:1.2},light:{strokeOpacity:.16,innerOpacity:.32,bloomOpacity:.3,innerShadow:`rgba(0, 0, 0, 0.14)`,saturation:1.95}},"pulse-outside":{dark:{strokeOpacity:.94,innerOpacity:.34,bloomOpacity:.3,innerShadow:`transparent`,saturation:1.2,brightness:1.9,hairlineOpacity:0},light:{strokeOpacity:1.96,innerOpacity:1.04,bloomOpacity:.42,innerShadow:`transparent`,saturation:.6,brightness:1.7,hairlineOpacity:0}},"pulse-inner":{dark:{strokeOpacity:1.54,innerOpacity:.44,bloomOpacity:.66,innerShadow:`transparent`,saturation:1.2,brightness:.75},light:{strokeOpacity:.32,innerOpacity:.4,bloomOpacity:.8,innerShadow:`transparent`,saturation:.75,brightness:1.3}}};({...rt.md.dark}),{...rt.md.light};var J={colorful:{border:[{color:`rgb(255, 50, 100)`,pos:`33% -7.4%`,size:`70px 40px`},{color:`rgb(40, 140, 255)`,pos:`12% -5%`,size:`60px 35px`},{color:`rgb(50, 200, 80)`,pos:`2.1% 68.3%`,size:`40px 70px`},{color:`rgb(30, 185, 170)`,pos:`2.1% 68.3%`,size:`20px 35px`},{color:`rgb(100, 70, 255)`,pos:`74.4% 100%`,size:`180px 32px`},{color:`rgb(40, 140, 255)`,pos:`55% 100%`,size:`85px 26px`},{color:`rgb(255, 120, 40)`,pos:`93.9% 0%`,size:`74px 32px`},{color:`rgb(240, 50, 180)`,pos:`100% 27.1%`,size:`26px 42px`},{color:`rgb(180, 40, 240)`,pos:`100% 27.1%`,size:`52px 48px`}],spike:{primary:`rgb(255, 60, 80)`,secondary:`rgba(40, 190, 180, 0.98)`},spikeLt:{primary:`rgb(200, 30, 60)`,secondary:`rgb(20, 150, 140)`}},mono:{border:[{color:`rgb(180, 180, 180)`,pos:`33% -7.4%`,size:`70px 40px`},{color:`rgb(140, 140, 140)`,pos:`12% -5%`,size:`60px 35px`},{color:`rgb(160, 160, 160)`,pos:`2.1% 68.3%`,size:`40px 70px`},{color:`rgb(130, 130, 130)`,pos:`2.1% 68.3%`,size:`20px 35px`},{color:`rgb(170, 170, 170)`,pos:`74.4% 100%`,size:`180px 32px`},{color:`rgb(150, 150, 150)`,pos:`55% 100%`,size:`85px 26px`},{color:`rgb(190, 190, 190)`,pos:`93.9% 0%`,size:`74px 32px`},{color:`rgb(145, 145, 145)`,pos:`100% 27.1%`,size:`26px 42px`},{color:`rgb(165, 165, 165)`,pos:`100% 27.1%`,size:`52px 48px`}],spike:{primary:`rgb(200, 200, 200)`,secondary:`rgb(170, 170, 170)`},spikeLt:{primary:`rgb(80, 80, 80)`,secondary:`rgb(120, 120, 120)`}},ocean:{border:[{color:`rgb(100, 80, 220)`,pos:`33% -7.4%`,size:`70px 40px`},{color:`rgb(60, 120, 255)`,pos:`12% -5%`,size:`60px 35px`},{color:`rgb(80, 100, 200)`,pos:`2.1% 68.3%`,size:`40px 70px`},{color:`rgb(50, 140, 220)`,pos:`2.1% 68.3%`,size:`20px 35px`},{color:`rgb(120, 80, 255)`,pos:`74.4% 100%`,size:`180px 32px`},{color:`rgb(70, 130, 255)`,pos:`55% 100%`,size:`85px 26px`},{color:`rgb(140, 100, 240)`,pos:`93.9% 0%`,size:`74px 32px`},{color:`rgb(90, 110, 230)`,pos:`100% 27.1%`,size:`26px 42px`},{color:`rgb(130, 70, 255)`,pos:`100% 27.1%`,size:`52px 48px`}],spike:{primary:`rgb(100, 120, 255)`,secondary:`rgba(130, 100, 220, 0.98)`},spikeLt:{primary:`rgb(60, 60, 180)`,secondary:`rgb(80, 100, 200)`}},sunset:{border:[{color:`rgb(255, 80, 50)`,pos:`33% -7.4%`,size:`70px 40px`},{color:`rgb(255, 160, 40)`,pos:`12% -5%`,size:`60px 35px`},{color:`rgb(255, 120, 60)`,pos:`2.1% 68.3%`,size:`40px 70px`},{color:`rgb(255, 200, 50)`,pos:`2.1% 68.3%`,size:`20px 35px`},{color:`rgb(255, 100, 80)`,pos:`74.4% 100%`,size:`180px 32px`},{color:`rgb(255, 180, 60)`,pos:`55% 100%`,size:`85px 26px`},{color:`rgb(255, 60, 60)`,pos:`93.9% 0%`,size:`74px 32px`},{color:`rgb(255, 140, 50)`,pos:`100% 27.1%`,size:`26px 42px`},{color:`rgb(255, 90, 70)`,pos:`100% 27.1%`,size:`52px 48px`}],spike:{primary:`rgb(255, 140, 80)`,secondary:`rgba(255, 100, 60, 0.98)`},spikeLt:{primary:`rgb(200, 80, 40)`,secondary:`rgb(220, 120, 30)`}}},it={colorful:{border:[{color:`rgb(50, 200, 80)`,pos:`2% 68%`,size:`9px 18px`},{color:`rgb(30, 185, 170)`,pos:`2% 68%`,size:`4px 8px`},{color:`rgb(255, 120, 40)`,pos:`72% -3%`,size:`59px 9px`},{color:`rgb(100, 70, 255)`,pos:`74% 100%`,size:`42px 7px`},{color:`rgb(240, 50, 180)`,pos:`100% 27%`,size:`10px 17px`},{color:`rgb(180, 40, 240)`,pos:`100% 27%`,size:`10px 18px`},{color:`rgb(40, 140, 255)`,pos:`100% 27%`,size:`5px 10px`},{color:`rgb(255, 50, 100)`,pos:`100% 27%`,size:`11px 12px`}],inner:[{color:`rgba(50, 200, 80, 0.5)`,pos:`2% 68%`,size:`9px 18px`},{color:`rgba(30, 185, 170, 0.45)`,pos:`2% 68%`,size:`4px 8px`},{color:`rgba(255, 120, 40, 0.35)`,pos:`72% -3%`,size:`59px 9px`},{color:`rgba(100, 70, 255, 0.35)`,pos:`74% 100%`,size:`42px 7px`},{color:`rgba(240, 50, 180, 0.3)`,pos:`100% 27%`,size:`10px 17px`},{color:`rgba(180, 40, 240, 0.4)`,pos:`100% 27%`,size:`10px 18px`},{color:`rgba(40, 140, 255, 0.3)`,pos:`100% 27%`,size:`5px 10px`},{color:`rgba(255, 50, 100, 0.3)`,pos:`100% 27%`,size:`11px 12px`}]},mono:{border:[{color:`rgb(160, 160, 160)`,pos:`2% 68%`,size:`9px 18px`},{color:`rgb(140, 140, 140)`,pos:`2% 68%`,size:`4px 8px`},{color:`rgb(180, 180, 180)`,pos:`72% -3%`,size:`59px 9px`},{color:`rgb(150, 150, 150)`,pos:`74% 100%`,size:`42px 7px`},{color:`rgb(170, 170, 170)`,pos:`100% 27%`,size:`10px 17px`},{color:`rgb(155, 155, 155)`,pos:`100% 27%`,size:`10px 18px`},{color:`rgb(145, 145, 145)`,pos:`100% 27%`,size:`5px 10px`},{color:`rgb(165, 165, 165)`,pos:`100% 27%`,size:`11px 12px`}],inner:[{color:`rgba(160, 160, 160, 0.25)`,pos:`2% 68%`,size:`9px 18px`},{color:`rgba(140, 140, 140, 0.22)`,pos:`2% 68%`,size:`4px 8px`},{color:`rgba(180, 180, 180, 0.17)`,pos:`72% -3%`,size:`59px 9px`},{color:`rgba(150, 150, 150, 0.17)`,pos:`74% 100%`,size:`42px 7px`},{color:`rgba(170, 170, 170, 0.15)`,pos:`100% 27%`,size:`10px 17px`},{color:`rgba(155, 155, 155, 0.20)`,pos:`100% 27%`,size:`10px 18px`},{color:`rgba(145, 145, 145, 0.15)`,pos:`100% 27%`,size:`5px 10px`},{color:`rgba(165, 165, 165, 0.15)`,pos:`100% 27%`,size:`11px 12px`}]},ocean:{border:[{color:`rgb(60, 140, 200)`,pos:`2% 68%`,size:`9px 18px`},{color:`rgb(50, 120, 180)`,pos:`2% 68%`,size:`4px 8px`},{color:`rgb(100, 80, 220)`,pos:`72% -3%`,size:`59px 9px`},{color:`rgb(80, 100, 255)`,pos:`74% 100%`,size:`42px 7px`},{color:`rgb(120, 70, 240)`,pos:`100% 27%`,size:`10px 17px`},{color:`rgb(90, 80, 220)`,pos:`100% 27%`,size:`10px 18px`},{color:`rgb(70, 110, 255)`,pos:`100% 27%`,size:`5px 10px`},{color:`rgb(110, 90, 230)`,pos:`100% 27%`,size:`11px 12px`}],inner:[{color:`rgba(60, 140, 200, 0.5)`,pos:`2% 68%`,size:`9px 18px`},{color:`rgba(50, 120, 180, 0.45)`,pos:`2% 68%`,size:`4px 8px`},{color:`rgba(100, 80, 220, 0.35)`,pos:`72% -3%`,size:`59px 9px`},{color:`rgba(80, 100, 255, 0.35)`,pos:`74% 100%`,size:`42px 7px`},{color:`rgba(120, 70, 240, 0.3)`,pos:`100% 27%`,size:`10px 17px`},{color:`rgba(90, 80, 220, 0.4)`,pos:`100% 27%`,size:`10px 18px`},{color:`rgba(70, 110, 255, 0.3)`,pos:`100% 27%`,size:`5px 10px`},{color:`rgba(110, 90, 230, 0.3)`,pos:`100% 27%`,size:`11px 12px`}]},sunset:{border:[{color:`rgb(255, 180, 50)`,pos:`2% 68%`,size:`9px 18px`},{color:`rgb(255, 150, 40)`,pos:`2% 68%`,size:`4px 8px`},{color:`rgb(255, 80, 60)`,pos:`72% -3%`,size:`59px 9px`},{color:`rgb(255, 100, 80)`,pos:`74% 100%`,size:`42px 7px`},{color:`rgb(255, 60, 80)`,pos:`100% 27%`,size:`10px 17px`},{color:`rgb(255, 120, 60)`,pos:`100% 27%`,size:`10px 18px`},{color:`rgb(255, 200, 50)`,pos:`100% 27%`,size:`5px 10px`},{color:`rgb(255, 90, 70)`,pos:`100% 27%`,size:`11px 12px`}],inner:[{color:`rgba(255, 180, 50, 0.5)`,pos:`2% 68%`,size:`9px 18px`},{color:`rgba(255, 150, 40, 0.45)`,pos:`2% 68%`,size:`4px 8px`},{color:`rgba(255, 80, 60, 0.35)`,pos:`72% -3%`,size:`59px 9px`},{color:`rgba(255, 100, 80, 0.35)`,pos:`74% 100%`,size:`42px 7px`},{color:`rgba(255, 60, 80, 0.3)`,pos:`100% 27%`,size:`10px 17px`},{color:`rgba(255, 120, 60, 0.4)`,pos:`100% 27%`,size:`10px 18px`},{color:`rgba(255, 200, 50, 0.3)`,pos:`100% 27%`,size:`5px 10px`},{color:`rgba(255, 90, 70, 0.3)`,pos:`100% 27%`,size:`11px 12px`}]}};function at(e){return it[e].border.map(e=>`radial-gradient(ellipse ${e.size} at ${e.pos}, ${e.color}, transparent)`).join(`,
    `)}function ot(e){return it[e].inner.map(e=>`radial-gradient(ellipse ${e.size} at ${e.pos}, ${e.color}, transparent)`).join(`,
    `)}function st(e){return J[e].border.map(e=>`radial-gradient(ellipse ${e.size} at ${e.pos}, ${e.color}, transparent)`).join(`,
    `)}function ct(e){let t=J[e],n=e===`mono`?.225:.45;return t.border.map(e=>{let t=e.color.replace(`rgb(`,`rgba(`).replace(`)`,`, ${n})`);return`radial-gradient(ellipse ${e.size.split(` `).map(e=>`${Math.round(parseInt(e)*.9)}px`).join(` `)} at ${e.pos}, ${t}, transparent)`}).join(`,
    `)}function lt(e,t){let n=J[e];return t?n.spike:n.spikeLt}var ut={colorful:{dark:[{color:`rgb(255, 50, 100)`,sizeW:36,sizeH:36,offsetX:0,offsetY:2},{color:`rgb(40, 180, 220)`,sizeW:30,sizeH:32,offsetX:39,offsetY:0},{color:`rgb(50, 200, 80)`,sizeW:33,sizeH:28,offsetX:-36,offsetY:2},{color:`rgb(180, 40, 240)`,sizeW:29,sizeH:34,offsetX:-54,offsetY:0},{color:`rgb(255, 160, 30)`,sizeW:27,sizeH:30,offsetX:51,offsetY:-1},{color:`rgb(100, 70, 255)`,sizeW:36,sizeH:24,offsetX:21,offsetY:1},{color:`rgb(40, 140, 255)`,sizeW:30,sizeH:22,offsetX:-21,offsetY:0},{color:`rgb(240, 50, 180)`,sizeW:25,sizeH:28,offsetX:66,offsetY:1},{color:`rgb(30, 185, 170)`,sizeW:23,sizeH:30,offsetX:-66,offsetY:-1}],light:[{color:`rgb(255, 50, 100)`,sizeW:45,sizeH:36,offsetX:0,offsetY:2},{color:`rgb(40, 140, 255)`,sizeW:35,sizeH:32,offsetX:65,offsetY:0},{color:`rgb(50, 200, 80)`,sizeW:40,sizeH:28,offsetX:-60,offsetY:2},{color:`rgb(180, 40, 240)`,sizeW:35,sizeH:34,offsetX:-90,offsetY:0},{color:`rgb(30, 185, 170)`,sizeW:38,sizeH:30,offsetX:85,offsetY:-1},{color:`rgb(100, 70, 255)`,sizeW:50,sizeH:24,offsetX:35,offsetY:1},{color:`rgb(40, 140, 255)`,sizeW:40,sizeH:22,offsetX:-35,offsetY:0},{color:`rgb(255, 120, 40)`,sizeW:35,sizeH:28,offsetX:110,offsetY:1},{color:`rgb(240, 50, 180)`,sizeW:30,sizeH:30,offsetX:-110,offsetY:-1}]},mono:{dark:[{color:`rgb(200, 200, 200)`,sizeW:36,sizeH:36,offsetX:0,offsetY:2},{color:`rgb(170, 170, 170)`,sizeW:30,sizeH:32,offsetX:39,offsetY:0},{color:`rgb(155, 155, 155)`,sizeW:33,sizeH:28,offsetX:-36,offsetY:2},{color:`rgb(185, 185, 185)`,sizeW:29,sizeH:34,offsetX:-54,offsetY:0},{color:`rgb(165, 165, 165)`,sizeW:27,sizeH:30,offsetX:51,offsetY:-1},{color:`rgb(180, 180, 180)`,sizeW:36,sizeH:24,offsetX:21,offsetY:1},{color:`rgb(160, 160, 160)`,sizeW:30,sizeH:22,offsetX:-21,offsetY:0},{color:`rgb(175, 175, 175)`,sizeW:25,sizeH:28,offsetX:66,offsetY:1},{color:`rgb(190, 190, 190)`,sizeW:23,sizeH:30,offsetX:-66,offsetY:-1}],light:[{color:`rgb(100, 100, 100)`,sizeW:45,sizeH:36,offsetX:0,offsetY:2},{color:`rgb(80, 80, 80)`,sizeW:35,sizeH:32,offsetX:65,offsetY:0},{color:`rgb(90, 90, 90)`,sizeW:40,sizeH:28,offsetX:-60,offsetY:2},{color:`rgb(70, 70, 70)`,sizeW:35,sizeH:34,offsetX:-90,offsetY:0},{color:`rgb(85, 85, 85)`,sizeW:38,sizeH:30,offsetX:85,offsetY:-1},{color:`rgb(95, 95, 95)`,sizeW:50,sizeH:24,offsetX:35,offsetY:1},{color:`rgb(75, 75, 75)`,sizeW:40,sizeH:22,offsetX:-35,offsetY:0},{color:`rgb(105, 105, 105)`,sizeW:35,sizeH:28,offsetX:110,offsetY:1},{color:`rgb(65, 65, 65)`,sizeW:30,sizeH:30,offsetX:-110,offsetY:-1}]},ocean:{dark:[{color:`rgb(100, 80, 220)`,sizeW:36,sizeH:36,offsetX:0,offsetY:2},{color:`rgb(60, 120, 255)`,sizeW:30,sizeH:32,offsetX:39,offsetY:0},{color:`rgb(80, 100, 200)`,sizeW:33,sizeH:28,offsetX:-36,offsetY:2},{color:`rgb(130, 70, 255)`,sizeW:29,sizeH:34,offsetX:-54,offsetY:0},{color:`rgb(70, 130, 255)`,sizeW:27,sizeH:30,offsetX:51,offsetY:-1},{color:`rgb(120, 80, 255)`,sizeW:36,sizeH:24,offsetX:21,offsetY:1},{color:`rgb(90, 110, 230)`,sizeW:30,sizeH:22,offsetX:-21,offsetY:0},{color:`rgb(110, 90, 240)`,sizeW:25,sizeH:28,offsetX:66,offsetY:1},{color:`rgb(140, 100, 255)`,sizeW:23,sizeH:30,offsetX:-66,offsetY:-1}],light:[{color:`rgb(80, 60, 200)`,sizeW:45,sizeH:36,offsetX:0,offsetY:2},{color:`rgb(50, 100, 220)`,sizeW:35,sizeH:32,offsetX:65,offsetY:0},{color:`rgb(70, 90, 190)`,sizeW:40,sizeH:28,offsetX:-60,offsetY:2},{color:`rgb(110, 60, 220)`,sizeW:35,sizeH:34,offsetX:-90,offsetY:0},{color:`rgb(60, 110, 230)`,sizeW:38,sizeH:30,offsetX:85,offsetY:-1},{color:`rgb(100, 70, 240)`,sizeW:50,sizeH:24,offsetX:35,offsetY:1},{color:`rgb(80, 100, 210)`,sizeW:40,sizeH:22,offsetX:-35,offsetY:0},{color:`rgb(90, 80, 225)`,sizeW:35,sizeH:28,offsetX:110,offsetY:1},{color:`rgb(120, 90, 245)`,sizeW:30,sizeH:30,offsetX:-110,offsetY:-1}]},sunset:{dark:[{color:`rgb(255, 100, 60)`,sizeW:36,sizeH:36,offsetX:0,offsetY:2},{color:`rgb(255, 180, 50)`,sizeW:30,sizeH:32,offsetX:39,offsetY:0},{color:`rgb(255, 140, 70)`,sizeW:33,sizeH:28,offsetX:-36,offsetY:2},{color:`rgb(255, 80, 80)`,sizeW:29,sizeH:34,offsetX:-54,offsetY:0},{color:`rgb(255, 200, 60)`,sizeW:27,sizeH:30,offsetX:51,offsetY:-1},{color:`rgb(255, 120, 50)`,sizeW:36,sizeH:24,offsetX:21,offsetY:1},{color:`rgb(255, 160, 80)`,sizeW:30,sizeH:22,offsetX:-21,offsetY:0},{color:`rgb(255, 90, 60)`,sizeW:25,sizeH:28,offsetX:66,offsetY:1},{color:`rgb(255, 70, 70)`,sizeW:23,sizeH:30,offsetX:-66,offsetY:-1}],light:[{color:`rgb(220, 80, 40)`,sizeW:45,sizeH:36,offsetX:0,offsetY:2},{color:`rgb(230, 150, 30)`,sizeW:35,sizeH:32,offsetX:65,offsetY:0},{color:`rgb(210, 110, 50)`,sizeW:40,sizeH:28,offsetX:-60,offsetY:2},{color:`rgb(200, 60, 60)`,sizeW:35,sizeH:34,offsetX:-90,offsetY:0},{color:`rgb(220, 170, 40)`,sizeW:38,sizeH:30,offsetX:85,offsetY:-1},{color:`rgb(210, 100, 30)`,sizeW:50,sizeH:24,offsetX:35,offsetY:1},{color:`rgb(230, 130, 60)`,sizeW:40,sizeH:22,offsetX:-35,offsetY:0},{color:`rgb(190, 70, 50)`,sizeW:35,sizeH:28,offsetX:110,offsetY:1},{color:`rgb(180, 50, 50)`,sizeW:30,sizeH:30,offsetX:-110,offsetY:-1}]}};function dt(e,t,n){return ut[e][t?`dark`:`light`].map(e=>{let t=e.offsetX===0?``:e.offsetX>0?` + ${e.offsetX}px`:` - ${Math.abs(e.offsetX)}px`,r=e.offsetY===0?``:e.offsetY>0?` + ${e.offsetY}px`:` - ${Math.abs(e.offsetY)}px`;return`radial-gradient(ellipse calc(${e.sizeW}px * var(--beam-w-${n})) calc(${e.sizeH}px * var(--beam-h-${n})) at calc(var(--beam-x-${n}) * 100%${t}) calc(100%${r}), ${e.color}, transparent)`}).join(`,
       `)}var ft={colorful:[{color:`rgba(255, 50, 100, 0.48)`,sizeW:33,sizeH:30,offsetX:0,offsetY:0},{color:`rgba(40, 180, 220, 0.42)`,sizeW:24,sizeH:26,offsetX:39,offsetY:-3},{color:`rgba(50, 200, 80, 0.48)`,sizeW:27,sizeH:24,offsetX:-36,offsetY:0},{color:`rgba(180, 40, 240, 0.42)`,sizeW:23,sizeH:28,offsetX:-54,offsetY:-2},{color:`rgba(255, 160, 30, 0.50)`,sizeW:24,sizeH:24,offsetX:51,offsetY:-1},{color:`rgba(100, 70, 255, 0.45)`,sizeW:30,sizeH:20,offsetX:21,offsetY:0},{color:`rgba(40, 140, 255, 0.40)`,sizeW:25,sizeH:18,offsetX:-21,offsetY:-2},{color:`rgba(240, 50, 180, 0.45)`,sizeW:21,sizeH:24,offsetX:66,offsetY:0},{color:`rgba(30, 185, 170, 0.52)`,sizeW:18,sizeH:26,offsetX:-66,offsetY:-1}],mono:[{color:`rgba(200, 200, 200, 0.48)`,sizeW:33,sizeH:30,offsetX:0,offsetY:0},{color:`rgba(170, 170, 170, 0.42)`,sizeW:24,sizeH:26,offsetX:39,offsetY:-3},{color:`rgba(155, 155, 155, 0.48)`,sizeW:27,sizeH:24,offsetX:-36,offsetY:0},{color:`rgba(185, 185, 185, 0.42)`,sizeW:23,sizeH:28,offsetX:-54,offsetY:-2},{color:`rgba(165, 165, 165, 0.50)`,sizeW:24,sizeH:24,offsetX:51,offsetY:-1},{color:`rgba(180, 180, 180, 0.45)`,sizeW:30,sizeH:20,offsetX:21,offsetY:0},{color:`rgba(160, 160, 160, 0.40)`,sizeW:25,sizeH:18,offsetX:-21,offsetY:-2},{color:`rgba(175, 175, 175, 0.45)`,sizeW:21,sizeH:24,offsetX:66,offsetY:0},{color:`rgba(190, 190, 190, 0.52)`,sizeW:18,sizeH:26,offsetX:-66,offsetY:-1}],ocean:[{color:`rgba(100, 80, 220, 0.48)`,sizeW:33,sizeH:30,offsetX:0,offsetY:0},{color:`rgba(60, 120, 255, 0.42)`,sizeW:24,sizeH:26,offsetX:39,offsetY:-3},{color:`rgba(80, 100, 200, 0.48)`,sizeW:27,sizeH:24,offsetX:-36,offsetY:0},{color:`rgba(130, 70, 255, 0.42)`,sizeW:23,sizeH:28,offsetX:-54,offsetY:-2},{color:`rgba(70, 130, 255, 0.50)`,sizeW:24,sizeH:24,offsetX:51,offsetY:-1},{color:`rgba(120, 80, 255, 0.45)`,sizeW:30,sizeH:20,offsetX:21,offsetY:0},{color:`rgba(90, 110, 230, 0.40)`,sizeW:25,sizeH:18,offsetX:-21,offsetY:-2},{color:`rgba(110, 90, 240, 0.45)`,sizeW:21,sizeH:24,offsetX:66,offsetY:0},{color:`rgba(140, 100, 255, 0.52)`,sizeW:18,sizeH:26,offsetX:-66,offsetY:-1}],sunset:[{color:`rgba(255, 100, 60, 0.48)`,sizeW:33,sizeH:30,offsetX:0,offsetY:0},{color:`rgba(255, 180, 50, 0.42)`,sizeW:24,sizeH:26,offsetX:39,offsetY:-3},{color:`rgba(255, 140, 70, 0.48)`,sizeW:27,sizeH:24,offsetX:-36,offsetY:0},{color:`rgba(255, 80, 80, 0.42)`,sizeW:23,sizeH:28,offsetX:-54,offsetY:-2},{color:`rgba(255, 200, 60, 0.50)`,sizeW:24,sizeH:24,offsetX:51,offsetY:-1},{color:`rgba(255, 120, 50, 0.45)`,sizeW:30,sizeH:20,offsetX:21,offsetY:0},{color:`rgba(255, 160, 80, 0.40)`,sizeW:25,sizeH:18,offsetX:-21,offsetY:-2},{color:`rgba(255, 90, 60, 0.45)`,sizeW:21,sizeH:24,offsetX:66,offsetY:0},{color:`rgba(255, 70, 70, 0.52)`,sizeW:18,sizeH:26,offsetX:-66,offsetY:-1}]};function pt(e,t){return ft[e].map(e=>{let n=e.offsetX===0?``:e.offsetX>0?` + ${e.offsetX}px`:` - ${Math.abs(e.offsetX)}px`,r=e.offsetY===0?``:` - ${Math.abs(e.offsetY)}px`;return`radial-gradient(ellipse calc(${e.sizeW}px * var(--beam-w-${t})) calc(${e.sizeH}px * var(--beam-h-${t})) at calc(var(--beam-x-${t}) * 100%${n}) calc(100%${r}), ${e.color}, transparent)`}).join(`,
    `)}var mt={colorful:{dark:{spikes:[{color1:`rgb(100, 70, 255)`,color2:`rgba(100, 70, 255, 1)`},{color1:`rgba(255, 170, 40, 0.59)`,color2:`rgba(255, 170, 40, 0.29)`},{color1:`rgb(50, 200, 100)`,color2:`rgba(50, 200, 100, 1)`},{color1:`rgba(200, 50, 240, 0.91)`,color2:`rgba(200, 50, 240, 0.45)`},{color1:`rgb(40, 140, 255)`,color2:`rgba(40, 140, 255, 1)`}]},light:{spikes:[{color1:`rgb(80, 50, 200)`,color2:`rgba(80, 50, 200, 0.8)`},{color1:`rgba(210, 130, 0, 0.7)`,color2:`rgba(210, 130, 0, 0.46)`},{color1:`rgb(30, 160, 70)`,color2:`rgba(30, 160, 70, 0.82)`},{color1:`rgb(160, 30, 190)`,color2:`rgba(160, 30, 190, 0.7)`},{color1:`rgb(30, 100, 200)`,color2:`rgba(30, 100, 200, 0.78)`}]}},mono:{dark:{spikes:[{color1:`rgb(200, 200, 200)`,color2:`rgba(200, 200, 200, 1)`},{color1:`rgba(180, 180, 180, 0.59)`,color2:`rgba(180, 180, 180, 0.29)`},{color1:`rgb(190, 190, 190)`,color2:`rgba(190, 190, 190, 1)`},{color1:`rgba(170, 170, 170, 0.91)`,color2:`rgba(170, 170, 170, 0.45)`},{color1:`rgb(185, 185, 185)`,color2:`rgba(185, 185, 185, 1)`}]},light:{spikes:[{color1:`rgb(80, 80, 80)`,color2:`rgba(80, 80, 80, 0.8)`},{color1:`rgba(100, 100, 100, 0.7)`,color2:`rgba(100, 100, 100, 0.46)`},{color1:`rgb(70, 70, 70)`,color2:`rgba(70, 70, 70, 0.82)`},{color1:`rgb(90, 90, 90)`,color2:`rgba(90, 90, 90, 0.7)`},{color1:`rgb(85, 85, 85)`,color2:`rgba(85, 85, 85, 0.78)`}]}},ocean:{dark:{spikes:[{color1:`rgb(100, 80, 255)`,color2:`rgb(100, 80, 255)`},{color1:`rgba(80, 130, 220, 0.59)`,color2:`rgba(80, 130, 220, 0.29)`},{color1:`rgb(60, 100, 255)`,color2:`rgb(60, 100, 255)`},{color1:`rgba(90, 120, 200, 0.91)`,color2:`rgba(90, 120, 200, 0.45)`},{color1:`rgb(120, 90, 255)`,color2:`rgb(120, 90, 255)`}]},light:{spikes:[{color1:`rgb(50, 40, 180)`,color2:`rgba(50, 40, 180, 0.8)`},{color1:`rgba(40, 80, 200, 0.7)`,color2:`rgba(40, 80, 200, 0.46)`},{color1:`rgb(30, 50, 190)`,color2:`rgba(30, 50, 190, 0.82)`},{color1:`rgb(60, 90, 180)`,color2:`rgba(60, 90, 180, 0.7)`},{color1:`rgb(70, 60, 200)`,color2:`rgba(70, 60, 200, 0.78)`}]}},sunset:{dark:{spikes:[{color1:`rgb(255, 100, 80)`,color2:`rgb(255, 100, 80)`},{color1:`rgba(255, 150, 80, 0.59)`,color2:`rgba(255, 150, 80, 0.29)`},{color1:`rgb(255, 80, 60)`,color2:`rgb(255, 80, 60)`},{color1:`rgba(255, 120, 50, 0.91)`,color2:`rgba(255, 120, 50, 0.45)`},{color1:`rgb(255, 140, 70)`,color2:`rgb(255, 140, 70)`}]},light:{spikes:[{color1:`rgb(200, 60, 30)`,color2:`rgba(200, 60, 30, 0.8)`},{color1:`rgba(220, 100, 20, 0.7)`,color2:`rgba(220, 100, 20, 0.46)`},{color1:`rgb(180, 40, 20)`,color2:`rgba(180, 40, 20, 0.82)`},{color1:`rgb(210, 80, 10)`,color2:`rgba(210, 80, 10, 0.7)`},{color1:`rgb(190, 70, 30)`,color2:`rgba(190, 70, 30, 0.78)`}]}}};function ht(e,t){let n=e.match(/^rgba\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*[\d.]+\s*\)$/);if(n)return`rgba(${n[1]}, ${n[2]}, ${n[3]}, ${t})`;let r=e.match(/^rgb\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)$/);return r?`rgba(${r[1]}, ${r[2]}, ${r[3]}, ${t})`:e}function Y(e,t){let n=e.match(/^rgba\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)$/);if(n)return`rgba(${n[1]}, ${n[2]}, ${n[3]}, ${(parseFloat(n[4])*t).toFixed(2)})`;let r=e.match(/^rgb\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)$/);return r?`rgba(${r[1]}, ${r[2]}, ${r[3]}, ${t.toFixed(2)})`:e}function gt(e,t,n){let r=lt(e,t),i=mt[e][t?`dark`:`light`],a=e===`mono`,o=a?.14:1,s=a?Y(r.primary,.14):r.primary,c=a?Y(r.primary,.09):r.primary,l=a?Y(r.secondary,.12):r.secondary,u=a?ht(r.secondary,.06):ht(r.secondary,.49),d=i.spikes.map(e=>a?{color1:Y(e.color1,o),color2:Y(e.color2,o*.7)}:e),f=a?`12px`:`0.8px`,p=a?`14px`:`2px`,m=a?`12px`:`1.2px`,h=a?`10px`:`0.6px`,g=a?`42px`:`92px`,_=a?`38px`:`72px`,v=a?`40px`:`85px`,y=a?`32px`:`60px`,b=a?`12px`:`1px`,x=a?`rgba(255, 255, 255, 0.5)`:`rgba(255, 255, 255, 1)`,S=a?`rgba(255, 255, 255, 0.45)`:`rgba(255, 255, 255, 0.9)`,C=a?`rgba(255, 255, 255, 0.25)`:`rgba(255, 255, 255, 0.5)`,w=a?`rgba(255, 255, 255, 0.15)`:`rgba(255, 255, 255, 0.3)`,T=a?`rgba(255, 255, 255, 0.06)`:`rgba(255, 255, 255, 0.12)`,E=a?`rgba(255, 255, 255, 0.015)`:`rgba(255, 255, 255, 0.03)`;return t?`radial-gradient(ellipse calc(${f} * var(--beam-spike-${n})) calc(${g} * var(--beam-h-${n})) at 8% calc(100% - 2px), ${s}, ${c} 30%, transparent 88%),
       radial-gradient(ellipse calc(10px * var(--beam-spike2-${n})) calc(35px * var(--beam-h-${n})) at 22% calc(100% - 4px), ${l}, ${u} 50%, transparent 95%),
       radial-gradient(ellipse calc(${p} * (2 - var(--beam-spike-${n}))) calc(${_} * var(--beam-h-${n})) at 36% calc(100% - 3px), ${d[0].color1}, ${d[0].color2} 40%, transparent 90%),
       radial-gradient(ellipse calc(14px * var(--beam-spike2-${n})) calc(28px * var(--beam-h-${n})) at 50% calc(100% - 2px), ${d[1].color1}, ${d[1].color2} 55%, transparent 96%),
       radial-gradient(ellipse calc(${m} * (2 - var(--beam-spike2-${n}))) calc(${v} * var(--beam-h-${n})) at 64% calc(100% - 4px), ${d[2].color1}, ${d[2].color2} 35%, transparent 89%),
       radial-gradient(ellipse calc(7px * var(--beam-spike-${n})) calc(45px * var(--beam-h-${n})) at 78% calc(100% - 2px), ${d[3].color1}, ${d[3].color2} 48%, transparent 94%),
       radial-gradient(ellipse calc(${h} * (2 - var(--beam-spike-${n}))) calc(${y} * var(--beam-h-${n})) at 92% calc(100% - 3px), ${d[4].color1}, ${d[4].color2} 42%, transparent 91%),
       radial-gradient(ellipse calc(21px * var(--beam-spike-${n})) calc(15px * var(--beam-spike2-${n})) at calc(var(--beam-x-${n}) * 100%) calc(100% + 1px), ${x} 0%, ${S} 20%, ${C} 50%, transparent 100%),
       radial-gradient(ellipse calc(42px * var(--beam-w-${n})) calc(40px * var(--beam-h-${n})) at calc(var(--beam-x-${n}) * 100%) 100%, ${w} 0%, ${T} 25%, ${E} 55%, transparent 80%)`:`radial-gradient(ellipse calc(${f} * var(--beam-spike-${n})) calc(${g} * var(--beam-h-${n})) at 8% calc(100% - 2px), ${s}, ${a?Y(r.primary,.11):ht(r.primary,.85)} 30%, transparent 88%),
       radial-gradient(ellipse calc(10px * var(--beam-spike2-${n})) calc(35px * var(--beam-h-${n})) at 22% calc(100% - 4px), ${l}, ${a?Y(r.secondary,.09):ht(r.secondary,.7)} 50%, transparent 95%),
       radial-gradient(ellipse calc(${p} * (2 - var(--beam-spike-${n}))) calc(${_} * var(--beam-h-${n})) at 36% calc(100% - 3px), ${d[0].color1}, ${d[0].color2} 40%, transparent 90%),
       radial-gradient(ellipse calc(14px * var(--beam-spike2-${n})) calc(28px * var(--beam-h-${n})) at 50% calc(100% - 2px), ${d[1].color1}, ${d[1].color2} 55%, transparent 96%),
       radial-gradient(ellipse calc(${m} * (2 - var(--beam-spike2-${n}))) calc(${v} * var(--beam-h-${n})) at 64% calc(100% - 4px), ${d[2].color1}, ${d[2].color2} 35%, transparent 89%),
       radial-gradient(ellipse calc(7px * var(--beam-spike-${n})) calc(45px * var(--beam-h-${n})) at 78% calc(100% - 2px), ${d[3].color1}, ${d[3].color2} 48%, transparent 94%),
       radial-gradient(ellipse calc(${b} * (2 - var(--beam-spike-${n}))) calc(${y} * var(--beam-h-${n})) at 92% calc(100% - 3px), ${d[4].color1}, ${d[4].color2} 42%, transparent 91%),
       radial-gradient(ellipse calc(50px * var(--beam-w-${n})) calc(32px * var(--beam-h-${n})) at calc(var(--beam-x-${n}) * 100%) calc(100%), rgba(0, 0, 0, 0.5) 0%, rgba(0, 0, 0, 0.18) 30%, rgba(0, 0, 0, 0.03) 60%, transparent 85%)`}var _t=[{region:1,quad:`tl`},{region:2,quad:`tl`},{region:3,quad:`bl`},{region:1,quad:`bl`},{region:2,quad:`br`},{region:3,quad:`br`},{region:1,quad:`tr`},{region:2,quad:`tr`},{region:3,quad:`tr`}],vt=[[65,35],[55,30],[35,65],[15,30],[173,28],[80,22],[69,28],[22,38],[47,44]],yt=[{ci:0,region:1,quad:`tl`,w:84,h:48},{ci:1,region:2,quad:`tl`,w:72,h:42},{ci:2,region:3,quad:`bl`,w:48,h:84},{ci:4,region:2,quad:`br`,w:216,h:38},{ci:5,region:3,quad:`br`,w:102,h:31},{ci:6,region:1,quad:`tr`,w:89,h:38},{ci:8,region:3,quad:`tr`,w:62,h:58}],bt=[{ci:0,region:1,quad:`tl`,w:80,h:19,x:`27%`,y:`0%`},{ci:6,region:2,quad:`tr`,w:74,h:11,x:`73%`,y:`-1%`},{ci:7,region:3,quad:`tr`,w:15,h:44,x:`100%`,y:`33%`},{ci:8,region:1,quad:`br`,w:19,h:38,x:`101%`,y:`72%`},{ci:4,region:2,quad:`br`,w:84,h:13,x:`67%`,y:`100%`},{ci:1,region:3,quad:`bl`,w:60,h:21,x:`24%`,y:`101%`},{ci:2,region:1,quad:`bl`,w:17,h:40,x:`0%`,y:`60%`},{ci:3,region:2,quad:`tl`,w:13,h:32,x:`-1%`,y:`28%`}],xt=[{ci:0,region:1,quad:`tl`,w:110,h:30,x:`27%`,y:`3%`},{ci:6,region:2,quad:`tr`,w:100,h:20,x:`73%`,y:`1%`},{ci:7,region:3,quad:`tr`,w:26,h:62,x:`100%`,y:`33%`},{ci:8,region:1,quad:`br`,w:30,h:56,x:`101%`,y:`72%`},{ci:4,region:2,quad:`br`,w:120,h:22,x:`67%`,y:`99%`},{ci:1,region:3,quad:`bl`,w:88,h:32,x:`24%`,y:`99%`},{ci:2,region:1,quad:`bl`,w:28,h:58,x:`0%`,y:`60%`}];function St(e,t,n){let r=e.match(/^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/);return`rgba(${r?`${r[1]}, ${r[2]}, ${r[3]}`:`255, 255, 255`}, var(--bop-${t}-${n}))`}function Ct(e,t,n,r,i,a,o,s){return`radial-gradient(ellipse calc(${t}px * var(--bw${r}-${s}) * var(--pulse-glow-sx, 1) * var(--pulse-glow-boost, 1)) calc(${n}px * var(--bh${r}-${s}) * var(--bgh-${s}) * var(--pulse-glow-sy, 1) * var(--pulse-glow-boost, 1)) at calc(${a} + var(--bx${r}-${s})) calc(${o} + var(--by${r}-${s})), ${St(e,i,s)}, transparent)`}function wt(e,t){return J[e].border.map((e,n)=>{let{region:r,quad:i}=_t[n],[a,o]=e.pos.split(` `),[s,c]=e.size.split(` `).map(parseFloat);return Ct(e.color,s,c,r,i,a,o,t)}).join(`,
    `)}function Tt(e,t,n){let r=J[e].border.map((e,n)=>{let{region:r,quad:i}=_t[n],[a,o]=e.pos.split(` `),[s,c]=vt[n];return Ct(e.color,s,c,r,i,a,o,t)}),i=n?`255, 255, 255`:`0, 0, 0`,a=n?.18:.08,o=[[`0%`,`0%`,`tl`],[`100%`,`0%`,`tr`],[`0%`,`100%`,`bl`],[`100%`,`100%`,`br`]].map(([e,n,r])=>`radial-gradient(ellipse 60px 60px at ${e} ${n}, rgba(${i}, calc(${a} * var(--bop-${r}-${t}))), transparent 70%)`);return[...r,...o].join(`,
    `)}function Et(e,t,n){let r=J[t].border;return e.map(e=>{let t=r[e.ci],[i,a]=t.pos.split(` `);return Ct(t.color,e.w,e.h,e.region,e.quad,e.x??i,e.y??a,n)}).join(`,
    `)}function Dt(e,t,n){let r=J[t].border,i=+n.toFixed(3);return e.map(e=>{let t=r[e.ci],[n,a]=t.pos.split(` `),o=e.x??n,s=e.y??a,c=t.color.match(/^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/),l=c?`${c[1]}, ${c[2]}, ${c[3]}`:`255, 255, 255`;return`radial-gradient(ellipse calc(${e.w}px * var(--pulse-glow-sx, 1) * var(--pulse-glow-boost, 1)) calc(${e.h}px * var(--pulse-glow-sy, 1) * var(--pulse-glow-boost, 1)) at ${o} ${s}, rgba(${l}, ${i}), transparent)`}).join(`,
    `)}function X(e){return`
[data-beam="${e}"][data-paused],
[data-beam="${e}"][data-paused]::after,
[data-beam="${e}"][data-paused]::before,
[data-beam="${e}"][data-paused] [data-beam-bloom] {
  animation-play-state: paused !important;
}`}function Ot(e){return`${[`bw1`,`bh1`,`bw2`,`bh2`,`bw3`,`bh3`,`bgh`,`bop-tl`,`bop-tr`,`bop-bl`,`bop-br`].map(t=>`@property --${t}-${e} {
  syntax: "<number>";
  initial-value: 1;
  inherits: true;
}`).join(`

`)}

${[`bx1`,`by1`,`bx2`,`by2`,`bx3`,`by3`].map(t=>`@property --${t}-${e} {
  syntax: "<length>";
  initial-value: 0px;
  inherits: true;
}`).join(`

`)}

@property --beam-opacity-${e} {
  syntax: "<number>";
  initial-value: 0;
  inherits: true;
}

@property --beam-hue-${e} {
  syntax: "<angle>";
  initial-value: 0deg;
  inherits: true;
}`}function kt(e,t,n){let r=t===`dark`,i=n/2.3;return e===`pulse-inner`?{sp:.28,dr:r?33:40,op:r?.48:.45,gh:r?.34:.22,bs:(r?1.9:2.6)*i,ss:(r?2.6:4.6)*i,ghs:(r?2.4:5.5)*i,huePeriod:16}:{sp:r?.28:.36,dr:r?14:19,op:r?.46:0,gh:r?.16:.58,bs:(r?2.3:3.7)*i,ss:(r?6.4:4.6)*i,ghs:(r?2.4:3.8)*i,huePeriod:14}}function At(e,t){let{sp:n,dr:r,op:i,gh:a,bs:o,ss:s,ghs:c}=t;return[{prop:`--bw1-${e}`,a:1-n,b:1+n*1.1,period:s*.9,delay:0,unit:``},{prop:`--bh1-${e}`,a:1+n*.9,b:1-n*.85,period:s*1.26,delay:0,unit:``},{prop:`--bx1-${e}`,a:-r,b:r*.9,period:o*1.6,delay:0,unit:`px`},{prop:`--by1-${e}`,a:r*.55,b:-r*.7,period:o*1.6,delay:0,unit:`px`},{prop:`--bw2-${e}`,a:1+n,b:1-n*.85,period:s*1.1,delay:0,unit:``},{prop:`--bh2-${e}`,a:1-n*.8,b:1+n*1.05,period:s*.81,delay:0,unit:``},{prop:`--bx2-${e}`,a:r*.8,b:-r*.9,period:o*1.88,delay:0,unit:`px`},{prop:`--by2-${e}`,a:-r,b:r*.65,period:o*1.88,delay:0,unit:`px`},{prop:`--bw3-${e}`,a:1-n*.6,b:1+n*1.15,period:s*.98,delay:0,unit:``},{prop:`--bh3-${e}`,a:1+n*.75,b:1-n,period:s*1.4,delay:0,unit:``},{prop:`--bx3-${e}`,a:-r*.6,b:r,period:o*1.45,delay:0,unit:`px`},{prop:`--by3-${e}`,a:-r*.85,b:r*.45,period:o*1.45,delay:0,unit:`px`},{prop:`--bgh-${e}`,a:1-a,b:1+a,period:c,delay:0,unit:``},{prop:`--bop-tl-${e}`,a:1-i,b:1,period:o,delay:0,unit:``},{prop:`--bop-tr-${e}`,a:1-i,b:1,period:o*1.32,delay:o*.28,unit:``},{prop:`--bop-bl-${e}`,a:1-i,b:1,period:o*.84,delay:o*.55,unit:``},{prop:`--bop-br-${e}`,a:1-i,b:1,period:o*1.58,delay:o*.83,unit:``}]}function jt(e,t,n,r,i,a){if(e!==`pulse-inner`&&e!==`pulse-outside`)return null;let o=kt(e,t,n);return{oscillators:At(a,o),hue:i?null:{prop:`--beam-hue-${a}`,range:360,period:o.huePeriod,continuous:!0}}}function Mt(e,t,n){return`  animation: ${t}-${e} ${n}s ease forwards;`}function Nt(e){let{size:t}=e;return t===`line`?Rt(e):t===`sm`?Pt(e):t===`pulse-inner`?It(e):t===`pulse-outside`?Lt(e):Ft(e)}function Pt(e){let{id:t,borderRadius:n,borderWidth:r,duration:i,strokeOpacity:a,innerOpacity:o,bloomOpacity:s,innerShadow:c,colorVariant:l,staticColors:u,brightness:d,saturation:f,hueRange:p,theme:m}=e,h=Math.max(0,n-r),g=l===`mono`?.5:1,_=a*g,v=o*g,y=s*g,b=u?``:`animation: beam-hue-shift-${t} 12s ease-in-out infinite;`,x=u?``:`
@keyframes beam-hue-shift-${t} {
  0% { filter: hue-rotate(calc(var(--beam-hue-base, 0deg) - ${p}deg)) brightness(${d.toFixed(2)}) saturate(${f.toFixed(2)}); }
  50% { filter: hue-rotate(calc(var(--beam-hue-base, 0deg) + ${p}deg)) brightness(${d.toFixed(2)}) saturate(${f.toFixed(2)}); }
  100% { filter: hue-rotate(calc(var(--beam-hue-base, 0deg) - ${p}deg)) brightness(${d.toFixed(2)}) saturate(${f.toFixed(2)}); }
}`,S=m===`dark`,C=S?`conic-gradient(
        from var(--beam-angle-${t}),
        transparent 0%, transparent 54%,
        rgba(255, 255, 255, 0.1) 57%,
        rgba(255, 255, 255, 0.3) 60%,
        rgba(255, 255, 255, 0.6) 63%,
        rgba(255, 255, 255, 0.75) 66%,
        rgba(255, 255, 255, 0.6) 69%,
        rgba(255, 255, 255, 0.3) 72%,
        rgba(255, 255, 255, 0.1) 75%,
        transparent 78%, transparent 100%
      )`:`conic-gradient(
        from var(--beam-angle-${t}),
        transparent 0%, transparent 54%,
        rgba(0, 0, 0, 0.08) 57%,
        rgba(0, 0, 0, 0.2) 60%,
        rgba(0, 0, 0, 0.4) 63%,
        rgba(0, 0, 0, 0.55) 66%,
        rgba(0, 0, 0, 0.4) 69%,
        rgba(0, 0, 0, 0.2) 72%,
        rgba(0, 0, 0, 0.08) 75%,
        transparent 78%, transparent 100%
      )`,w=at(l),T=ot(l),E=S?`conic-gradient(
        from var(--beam-angle-${t}),
        transparent 0%, transparent 58%,
        rgba(255, 255, 255, 0.03) 62%,
        rgba(255, 255, 255, 0.08) 65%,
        rgba(255, 255, 255, 0.2) 67%,
        rgba(255, 255, 255, 0.45) 69%,
        rgba(255, 255, 255, 0.85) 70%,
        rgba(255, 255, 255, 0.85) 70.5%,
        rgba(255, 255, 255, 0.45) 71.5%,
        rgba(255, 255, 255, 0.2) 73%,
        rgba(255, 255, 255, 0.08) 75%,
        rgba(255, 255, 255, 0.03) 78%,
        transparent 82%
      )`:`conic-gradient(
        from var(--beam-angle-${t}),
        transparent 0%, transparent 58%,
        rgba(0, 0, 0, 0.02) 62%,
        rgba(0, 0, 0, 0.08) 65%,
        rgba(0, 0, 0, 0.2) 67%,
        rgba(0, 0, 0, 0.4) 69%,
        rgba(0, 0, 0, 0.6) 70%,
        rgba(0, 0, 0, 0.6) 70.5%,
        rgba(0, 0, 0, 0.4) 71.5%,
        rgba(0, 0, 0, 0.2) 73%,
        rgba(0, 0, 0, 0.08) 75%,
        rgba(0, 0, 0, 0.02) 78%,
        transparent 82%
      )`,D=`conic-gradient(
    from var(--beam-angle-${t}),
    transparent 0%, transparent 22%,
    rgba(255, 255, 255, 0.12) 28%, rgba(255, 255, 255, 0.4) 36%,
    white 46%, white 82%,
    rgba(255, 255, 255, 0.4) 88%, rgba(255, 255, 255, 0.12) 94%,
    transparent 97%, transparent 100%
  )`;return`
@property --beam-angle-${t} {
  syntax: "<angle>";
  initial-value: 0deg;
  inherits: true;
}

@property --beam-opacity-${t} {
  syntax: "<number>";
  initial-value: 0;
  inherits: true;
}

[data-beam="${t}"] {
  position: relative;
  border-radius: ${n}px;
  overflow: hidden;
}

[data-beam="${t}"][data-active] {
  animation:
    beam-spin-${t} ${i}s linear infinite,
    beam-fade-in-${t} 0.6s ease forwards;
}

[data-beam="${t}"][data-fading] {
  animation:
    beam-spin-${t} ${i}s linear infinite,
    beam-fade-out-${t} 0.5s ease forwards;
}

[data-beam="${t}"][data-active]::after,
[data-beam="${t}"][data-fading]::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${h}px;
  padding: ${r}px;
  clip-path: inset(0 round ${n}px);
  background: ${C},${w};
  -webkit-mask:
    conic-gradient(
      from var(--beam-angle-${t}),
      transparent 0%, transparent 30%,
      rgba(255, 255, 255, 0.1) 36%, rgba(255, 255, 255, 0.35) 44%,
      white 52%, white 80%,
      rgba(255, 255, 255, 0.35) 86%, rgba(255, 255, 255, 0.1) 92%,
      transparent 95%, transparent 100%
    ),
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  -webkit-mask-composite: source-in, xor;
  mask:
    conic-gradient(
      from var(--beam-angle-${t}),
      transparent 0%, transparent 30%,
      rgba(255, 255, 255, 0.1) 36%, rgba(255, 255, 255, 0.35) 44%,
      white 52%, white 80%,
      rgba(255, 255, 255, 0.35) 86%, rgba(255, 255, 255, 0.1) 92%,
      transparent 95%, transparent 100%
    ),
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  mask-composite: intersect, exclude;
  pointer-events: none;
  z-index: 2;
  opacity: calc(var(--beam-opacity-${t}) * ${_.toFixed(2)} * var(--beam-stroke-opacity, 1) * var(--beam-strength, 1));
  ${b}
}

[data-beam="${t}"][data-active]::before,
[data-beam="${t}"][data-fading]::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${n}px;
  clip-path: inset(0 round ${n}px);
  background: ${T};
  box-shadow: inset 0 0 5px 1px ${c};
  -webkit-mask-image: ${D};
  -webkit-mask-composite: source-over;
  mask-image: ${D};
  mask-composite: add;
  pointer-events: none;
  z-index: 1;
  opacity: calc(var(--beam-opacity-${t}) * ${v.toFixed(2)} * var(--beam-inner-opacity, 1) * var(--beam-strength, 1));
  ${b}
}

[data-beam="${t}"] [data-beam-bloom] {
  display: none;
  position: absolute;
  inset: 0;
  border-radius: ${h}px;
  clip-path: inset(0 round ${n}px);
  background: ${E};
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask-composite: exclude;
  padding: ${r}px;
  filter: blur(8px) brightness(${d.toFixed(2)}) saturate(${f.toFixed(2)});
  pointer-events: none;
  z-index: 3;
  opacity: 0;
}

[data-beam="${t}"][data-active] [data-beam-bloom],
[data-beam="${t}"][data-fading] [data-beam-bloom] {
  display: block;
  opacity: calc(var(--beam-opacity-${t}) * ${y.toFixed(2)} * var(--beam-bloom-opacity, 1) * var(--beam-strength, 1));
}

@keyframes beam-spin-${t} {
  to { --beam-angle-${t}: 360deg; }
}

@keyframes beam-fade-in-${t} {
  to { --beam-opacity-${t}: 1; }
}

@keyframes beam-fade-out-${t} {
  from { --beam-opacity-${t}: 1; }
  to { --beam-opacity-${t}: 0; }
}
${x}
${X(t)}
`}function Ft(e){let{id:t,borderRadius:n,borderWidth:r,duration:i,strokeOpacity:a,innerOpacity:o,bloomOpacity:s,innerShadow:c,colorVariant:l,staticColors:u,brightness:d,saturation:f,hueRange:p,theme:m}=e,h=Math.max(0,n-r),g=l===`mono`?.5:1,_=a*g,v=o*g,y=s*g,b=u?``:`animation: beam-hue-shift-${t} 12s ease-in-out infinite;`,x=u?``:`
@keyframes beam-hue-shift-${t} {
  0% { filter: hue-rotate(calc(var(--beam-hue-base, 0deg) - ${p}deg)) brightness(${d.toFixed(2)}) saturate(${f.toFixed(2)}); }
  50% { filter: hue-rotate(calc(var(--beam-hue-base, 0deg) + ${p}deg)) brightness(${d.toFixed(2)}) saturate(${f.toFixed(2)}); }
  100% { filter: hue-rotate(calc(var(--beam-hue-base, 0deg) - ${p}deg)) brightness(${d.toFixed(2)}) saturate(${f.toFixed(2)}); }
}`,S=m===`dark`,C=S?`conic-gradient(
        from var(--beam-angle-${t}),
        transparent 0%, transparent 54%,
        rgba(255, 255, 255, 0.1) 57%,
        rgba(255, 255, 255, 0.3) 60%,
        rgba(255, 255, 255, 0.6) 63%,
        rgba(255, 255, 255, 0.75) 66%,
        rgba(255, 255, 255, 0.6) 69%,
        rgba(255, 255, 255, 0.3) 72%,
        rgba(255, 255, 255, 0.1) 75%,
        transparent 78%, transparent 100%
      )`:`conic-gradient(
        from var(--beam-angle-${t}),
        transparent 0%, transparent 54%,
        rgba(0, 0, 0, 0.08) 57%,
        rgba(0, 0, 0, 0.2) 60%,
        rgba(0, 0, 0, 0.4) 63%,
        rgba(0, 0, 0, 0.55) 66%,
        rgba(0, 0, 0, 0.4) 69%,
        rgba(0, 0, 0, 0.2) 72%,
        rgba(0, 0, 0, 0.08) 75%,
        transparent 78%, transparent 100%
      )`,w=st(l),T=ct(l),E=S?`conic-gradient(
        from var(--beam-angle-${t}),
        transparent 0%, transparent 58%,
        rgba(255, 255, 255, 0.03) 62%,
        rgba(255, 255, 255, 0.08) 65%,
        rgba(255, 255, 255, 0.2) 67%,
        rgba(255, 255, 255, 0.45) 69%,
        rgba(255, 255, 255, 0.85) 70%,
        rgba(255, 255, 255, 0.85) 70.5%,
        rgba(255, 255, 255, 0.45) 71.5%,
        rgba(255, 255, 255, 0.2) 73%,
        rgba(255, 255, 255, 0.08) 75%,
        rgba(255, 255, 255, 0.03) 78%,
        transparent 82%
      )`:`conic-gradient(
        from var(--beam-angle-${t}),
        transparent 0%, transparent 58%,
        rgba(0, 0, 0, 0.02) 62%,
        rgba(0, 0, 0, 0.08) 65%,
        rgba(0, 0, 0, 0.2) 67%,
        rgba(0, 0, 0, 0.4) 69%,
        rgba(0, 0, 0, 0.6) 70%,
        rgba(0, 0, 0, 0.6) 70.5%,
        rgba(0, 0, 0, 0.4) 71.5%,
        rgba(0, 0, 0, 0.2) 73%,
        rgba(0, 0, 0, 0.08) 75%,
        rgba(0, 0, 0, 0.02) 78%,
        transparent 82%
      )`;return`
@property --beam-angle-${t} {
  syntax: "<angle>";
  initial-value: 0deg;
  inherits: true;
}

@property --beam-opacity-${t} {
  syntax: "<number>";
  initial-value: 0;
  inherits: true;
}

[data-beam="${t}"] {
  position: relative;
  border-radius: ${n}px;
  overflow: hidden;
}

[data-beam="${t}"][data-active] {
  animation:
    beam-spin-${t} ${i}s linear infinite,
    beam-fade-in-${t} 0.6s ease forwards;
}

[data-beam="${t}"][data-fading] {
  animation:
    beam-spin-${t} ${i}s linear infinite,
    beam-fade-out-${t} 0.5s ease forwards;
}

[data-beam="${t}"][data-active]::after,
[data-beam="${t}"][data-fading]::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${h}px;
  padding: ${r}px;
  clip-path: inset(0 round ${n}px);
  background: ${C},${w};
  -webkit-mask:
    conic-gradient(
      from var(--beam-angle-${t}),
      transparent 0%, transparent 30%,
      rgba(255, 255, 255, 0.1) 36%, rgba(255, 255, 255, 0.35) 44%,
      white 52%, white 80%,
      rgba(255, 255, 255, 0.35) 86%, rgba(255, 255, 255, 0.1) 92%,
      transparent 95%, transparent 100%
    ),
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  -webkit-mask-composite: source-in, xor;
  mask:
    conic-gradient(
      from var(--beam-angle-${t}),
      transparent 0%, transparent 30%,
      rgba(255, 255, 255, 0.1) 36%, rgba(255, 255, 255, 0.35) 44%,
      white 52%, white 80%,
      rgba(255, 255, 255, 0.35) 86%, rgba(255, 255, 255, 0.1) 92%,
      transparent 95%, transparent 100%
    ),
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  mask-composite: intersect, exclude;
  pointer-events: none;
  z-index: 2;
  opacity: calc(var(--beam-opacity-${t}) * ${_.toFixed(2)} * var(--beam-stroke-opacity, 1) * var(--beam-strength, 1));
  ${b}
}

[data-beam="${t}"][data-active]::before,
[data-beam="${t}"][data-fading]::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${n}px;
  background: ${T};
  box-shadow: inset 0 0 9px 1px ${c};
  -webkit-mask-image:
    conic-gradient(
      from var(--beam-angle-${t}),
      transparent 0%, transparent 30%,
      rgba(255, 255, 255, 0.1) 36%, rgba(255, 255, 255, 0.35) 44%,
      white 52%, white 80%,
      rgba(255, 255, 255, 0.35) 86%, rgba(255, 255, 255, 0.1) 92%,
      transparent 95%, transparent 100%
    ),
    linear-gradient(white, transparent 28px, transparent calc(100% - 28px), white),
    linear-gradient(to right, white, transparent 28px, transparent calc(100% - 28px), white);
  -webkit-mask-composite: source-in, source-over;
  mask-image:
    conic-gradient(
      from var(--beam-angle-${t}),
      transparent 0%, transparent 30%,
      rgba(255, 255, 255, 0.1) 36%, rgba(255, 255, 255, 0.35) 44%,
      white 52%, white 80%,
      rgba(255, 255, 255, 0.35) 86%, rgba(255, 255, 255, 0.1) 92%,
      transparent 95%, transparent 100%
    ),
    linear-gradient(white, transparent 28px, transparent calc(100% - 28px), white),
    linear-gradient(to right, white, transparent 28px, transparent calc(100% - 28px), white);
  mask-composite: intersect, add;
  pointer-events: none;
  z-index: 1;
  opacity: calc(var(--beam-opacity-${t}) * ${v.toFixed(2)} * var(--beam-inner-opacity, 1) * var(--beam-strength, 1));
  clip-path: inset(0 round ${n}px);
  ${b}
}

[data-beam="${t}"] [data-beam-bloom] {
  display: none;
  position: absolute;
  inset: 0;
  border-radius: ${h}px;
  clip-path: inset(0 round ${n}px);
  background: ${E};
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask-composite: exclude;
  padding: ${r}px;
  filter: blur(8px) brightness(${d.toFixed(2)}) saturate(${f.toFixed(2)});
  pointer-events: none;
  z-index: 3;
  opacity: 0;
}

[data-beam="${t}"][data-active] [data-beam-bloom],
[data-beam="${t}"][data-fading] [data-beam-bloom] {
  display: block;
  opacity: calc(var(--beam-opacity-${t}) * ${y.toFixed(2)} * var(--beam-bloom-opacity, 1) * var(--beam-strength, 1));
}

@keyframes beam-spin-${t} {
  to { --beam-angle-${t}: 360deg; }
}

@keyframes beam-fade-in-${t} {
  to { --beam-opacity-${t}: 1; }
}

@keyframes beam-fade-out-${t} {
  from { --beam-opacity-${t}: 1; }
  to { --beam-opacity-${t}: 0; }
}
${x}
${X(t)}
`}function It(e){let{id:t,borderRadius:n,borderWidth:r,duration:i,strokeOpacity:a,innerOpacity:o,bloomOpacity:s,colorVariant:c,staticColors:l,brightness:u,saturation:d,hueRange:f,theme:p}=e,m=p===`dark`,h=c===`mono`?.5:1,g=(a*h).toFixed(2),_=(o*h).toFixed(2),v=(s*h).toFixed(2),{op:y}=kt(`pulse-inner`,p,i),b=u.toFixed(2),x=d.toFixed(2),S=l?`filter: brightness(${b}) saturate(${x});`:`filter: hue-rotate(calc(var(--beam-hue-base, 0deg) + var(--beam-hue-${t}))) brightness(${b}) saturate(${x});`,C=l?`filter: blur(8px) brightness(${b}) saturate(${x});`:`filter: blur(8px) hue-rotate(calc(var(--beam-hue-base, 0deg) + var(--beam-hue-${t}))) brightness(${b}) saturate(${x});`,w=wt(c,t),T=Tt(c,t,m),E=Dt(yt,c,1-y*.5);return`
${Ot(t)}

[data-beam="${t}"] {
  position: relative;
  border-radius: ${n}px;
  overflow: hidden;
  isolation: isolate;
}

[data-beam="${t}"][data-active] {
${Mt(t,`beam-fade-in`,.6)}
}

[data-beam="${t}"][data-fading] {
${Mt(t,`beam-fade-out`,.5)}
}

[data-beam="${t}"][data-active]::after,
[data-beam="${t}"][data-fading]::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${n}px;
  padding: ${r}px;
  clip-path: inset(0 round ${n}px);
  background: ${w};
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask-composite: exclude;
  pointer-events: none;
  z-index: 2;
  will-change: opacity, filter;
  opacity: calc(var(--beam-opacity-${t}) * ${g} * var(--beam-stroke-opacity, 1) * var(--beam-strength, 1));
  ${S}
}

[data-beam="${t}"][data-active]::before,
[data-beam="${t}"][data-fading]::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${n}px;
  clip-path: inset(0 round ${n}px);
  background: ${T};
  -webkit-mask-image:
    linear-gradient(white, transparent 28px, transparent calc(100% - 28px), white),
    linear-gradient(to right, white, transparent 28px, transparent calc(100% - 28px), white);
  -webkit-mask-composite: source-over;
  mask-image:
    linear-gradient(white, transparent 28px, transparent calc(100% - 28px), white),
    linear-gradient(to right, white, transparent 28px, transparent calc(100% - 28px), white);
  mask-composite: add;
  pointer-events: none;
  z-index: 1;
  will-change: opacity, filter;
  opacity: calc(var(--beam-opacity-${t}) * ${_} * var(--beam-inner-opacity, 1) * var(--beam-strength, 1));
  ${S}
}

[data-beam="${t}"] [data-beam-bloom] {
  display: none;
  position: absolute;
  inset: 0;
  border-radius: ${n}px;
  clip-path: inset(0 round ${n}px);
  background: ${E};
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask-composite: exclude;
  padding: ${r}px;
  pointer-events: none;
  z-index: 3;
  will-change: opacity;
  opacity: 0;
}

[data-beam="${t}"][data-active] [data-beam-bloom],
[data-beam="${t}"][data-fading] [data-beam-bloom] {
  display: block;
  opacity: calc(var(--beam-opacity-${t}) * ${v} * var(--beam-bloom-opacity, 1) * var(--beam-strength, 1));
  ${C}
}

@keyframes beam-fade-in-${t} { to { --beam-opacity-${t}: 1; } }
@keyframes beam-fade-out-${t} { from { --beam-opacity-${t}: 1; } to { --beam-opacity-${t}: 0; } }
${X(t)}

@media (prefers-reduced-motion: reduce) {
  [data-beam="${t}"][data-active],
  [data-beam="${t}"][data-fading],
  [data-beam="${t}"][data-active]::after,
  [data-beam="${t}"][data-fading]::after,
  [data-beam="${t}"][data-active]::before,
  [data-beam="${t}"][data-fading]::before,
  [data-beam="${t}"][data-active] [data-beam-bloom],
  [data-beam="${t}"][data-fading] [data-beam-bloom] {
    animation: none !important;
  }
}
`}function Lt(e){let{id:t,borderRadius:n,duration:r,strokeOpacity:i,innerOpacity:a,bloomOpacity:o,colorVariant:s,staticColors:c,brightness:l,saturation:u,hueRange:d,theme:f,hairlineOpacity:p=0}=e,m=f===`dark`,h=s===`mono`?.5:1,g=(i*h).toFixed(2),_=(a*h).toFixed(2),v=(o*h).toFixed(2),y=m?`70, 70, 70`:`0, 0, 0`,b=p.toFixed(2),x=`linear-gradient(rgba(${y}, ${b}), rgba(${y}, ${b}))`,{op:S}=kt(`pulse-outside`,f,r),C=.95,w=.9,T=m?3:6,E=m?22.5:15,D=l.toFixed(2),O=u.toFixed(2),ee=c?`filter: brightness(${D}) saturate(${O});`:`filter: hue-rotate(calc(var(--beam-hue-base, 0deg) + var(--beam-hue-${t}))) brightness(${D}) saturate(${O});`,k=`brightness(var(--beam-glow-brightness, ${D})) saturate(var(--beam-glow-saturate, ${O}))`,A=c?`filter: blur(var(--beam-core-blur, ${T}px)) ${k};`:`filter: blur(var(--beam-core-blur, ${T}px)) hue-rotate(calc(var(--beam-hue-base, 0deg) + var(--beam-hue-${t}))) ${k};`,j=c?`filter: blur(var(--beam-bloom-blur, ${E}px)) ${k};`:`filter: blur(var(--beam-bloom-blur, ${E}px)) hue-rotate(calc(var(--beam-hue-base, 0deg) + var(--beam-hue-${t}))) ${k};`,M=Et(bt,s,t),N=Et(bt,s,t),P=Dt(xt,s,1-S*.5),F=p>0?`${M},
    ${x}`:M;return`
${Ot(t)}

[data-beam="${t}"] {
  position: relative;
  border-radius: ${n}px;
  overflow: visible;
  isolation: isolate;
}

[data-beam="${t}"][data-active] {
${Mt(t,`beam-fade-in`,.6)}
}

[data-beam="${t}"][data-fading] {
${Mt(t,`beam-fade-out`,.5)}
}
${p>0?`
/* Idle hairline — painted above the (opaque) child in the inner 1px edge ring so
   it overlaps a standard inset component border exactly. */
[data-beam="${t}"]::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${n}px;
  padding: 1px;
  clip-path: inset(0 round ${n}px);
  background: ${x};
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask-composite: exclude;
  pointer-events: none;
  z-index: 2;
}
`:``}
[data-beam="${t}"][data-active]::after,
[data-beam="${t}"][data-fading]::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${n}px;
  padding: 1px;
  clip-path: inset(0 round ${n}px);
  background: ${F};
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask-composite: exclude;
  pointer-events: none;
  z-index: 2;
  will-change: opacity, filter;
  opacity: calc(var(--beam-opacity-${t}) * ${g} * var(--beam-stroke-opacity, 1) * var(--beam-strength, 1));
  ${ee}
}

[data-beam="${t}"][data-active]::before,
[data-beam="${t}"][data-fading]::before {
  content: "";
  position: absolute;
  inset: -10px;
  z-index: -1;
  border-radius: ${n+10}px;
  background: ${N};
  transform: scale(${C}, ${w});
  pointer-events: none;
  will-change: opacity, filter;
  opacity: calc(var(--beam-opacity-${t}) * ${_} * var(--beam-inner-opacity, 1) * var(--beam-strength, 1));
  ${A}
}

[data-beam="${t}"] [data-beam-bloom] {
  display: none;
  position: absolute;
  inset: -30px;
  z-index: -1;
  border-radius: ${n+30}px;
  background: ${P};
  transform: scale(${C}, ${w});
  pointer-events: none;
  will-change: transform;
  opacity: 0;
}

[data-beam="${t}"][data-active] [data-beam-bloom],
[data-beam="${t}"][data-fading] [data-beam-bloom] {
  display: block;
  opacity: calc(var(--beam-opacity-${t}) * ${v} * var(--beam-bloom-opacity, 1) * var(--beam-strength, 1));
  ${j}
}

@keyframes beam-fade-in-${t} { to { --beam-opacity-${t}: 1; } }
@keyframes beam-fade-out-${t} { from { --beam-opacity-${t}: 1; } to { --beam-opacity-${t}: 0; } }
${X(t)}

@media (prefers-reduced-motion: reduce) {
  [data-beam="${t}"][data-active],
  [data-beam="${t}"][data-fading],
  [data-beam="${t}"][data-active]::after,
  [data-beam="${t}"][data-fading]::after,
  [data-beam="${t}"][data-active]::before,
  [data-beam="${t}"][data-fading]::before,
  [data-beam="${t}"][data-active] [data-beam-bloom],
  [data-beam="${t}"][data-fading] [data-beam-bloom] {
    animation: none !important;
  }
}
`}function Rt(e){let{id:t,borderRadius:n,borderWidth:r,duration:i,strokeOpacity:a,innerOpacity:o,bloomOpacity:s,innerShadow:c,colorVariant:l,staticColors:u,brightness:d,saturation:f,hueRange:p,theme:m}=e,h=Math.max(0,n-r),g=m===`dark`,_=a,v=o,y=s,b=u?``:`animation: beam-hue-shift-${t} 12s ease-in-out infinite;`,x=u?``:`animation: beam-hue-shift-bloom-${t} 8s ease-in-out infinite;`,S=u?``:`
@keyframes beam-hue-shift-${t} {
  0% { filter: hue-rotate(calc(var(--beam-hue-base, 0deg) - ${p}deg)) brightness(${d.toFixed(2)}) saturate(${f.toFixed(2)}); }
  50% { filter: hue-rotate(calc(var(--beam-hue-base, 0deg) + ${p}deg)) brightness(${d.toFixed(2)}) saturate(${f.toFixed(2)}); }
  100% { filter: hue-rotate(calc(var(--beam-hue-base, 0deg) - ${p}deg)) brightness(${d.toFixed(2)}) saturate(${f.toFixed(2)}); }
}

@keyframes beam-hue-shift-bloom-${t} {
  0% { filter: blur(8px) hue-rotate(calc(var(--beam-hue-base, 0deg) - ${p+10}deg)) brightness(${d.toFixed(2)}) saturate(${f.toFixed(2)}); }
  50% { filter: blur(8px) hue-rotate(calc(var(--beam-hue-base, 0deg) + ${p+10}deg)) brightness(${d.toFixed(2)}) saturate(${f.toFixed(2)}); }
  100% { filter: blur(8px) hue-rotate(calc(var(--beam-hue-base, 0deg) - ${p+10}deg)) brightness(${d.toFixed(2)}) saturate(${f.toFixed(2)}); }
}`,C=g?`radial-gradient(
        ellipse calc(24px * var(--beam-w-${t})) calc(28px * var(--beam-h-${t})) at calc(var(--beam-x-${t}) * 100%) calc(100% + 2px),
        rgba(255, 255, 255, 0.38) 0%,
        rgba(255, 255, 255, 0.12) 30%,
        transparent 65%
      )`:`radial-gradient(
        ellipse calc(35px * var(--beam-w-${t})) calc(28px * var(--beam-h-${t})) at calc(var(--beam-x-${t}) * 100%) calc(100% + 2px),
        rgba(0, 0, 0, 0.6) 0%,
        rgba(0, 0, 0, 0.25) 35%,
        transparent 70%
      )`,w=dt(l,g,t),T=pt(l,t),E=gt(l,g,t),D=l===`mono`?`filter: blur(6px);`:``;return`
@property --beam-x-${t} {
  syntax: "<number>";
  initial-value: 0;
  inherits: true;
}

@property --beam-w-${t} {
  syntax: "<number>";
  initial-value: 1;
  inherits: true;
}

@property --beam-h-${t} {
  syntax: "<number>";
  initial-value: 1;
  inherits: true;
}

@property --beam-spike-${t} {
  syntax: "<number>";
  initial-value: 1;
  inherits: true;
}

@property --beam-spike2-${t} {
  syntax: "<number>";
  initial-value: 1;
  inherits: true;
}

@property --beam-edge-${t} {
  syntax: "<number>";
  initial-value: 1;
  inherits: true;
}

@property --beam-opacity-${t} {
  syntax: "<number>";
  initial-value: 0;
  inherits: true;
}

[data-beam="${t}"] {
  position: relative;
  border-radius: ${n}px;
  overflow: hidden;
}

[data-beam="${t}"][data-active] {
  animation:
    beam-travel-${t} ${i}s linear infinite,
    beam-edge-fade-${t} ${i}s linear infinite,
    beam-breathe-${t} ${(i*1.3).toFixed(1)}s ease-in-out infinite,
    beam-spike-${t} ${(i*1.33).toFixed(1)}s ease-in-out infinite,
    beam-spike2-${t} ${(i*1.7).toFixed(1)}s ease-in-out infinite,
    beam-fade-in-${t} 0.6s ease forwards;
}

[data-beam="${t}"][data-fading] {
  animation:
    beam-travel-${t} ${i}s linear infinite,
    beam-edge-fade-${t} ${i}s linear infinite,
    beam-breathe-${t} ${(i*1.3).toFixed(1)}s ease-in-out infinite,
    beam-spike-${t} ${(i*1.33).toFixed(1)}s ease-in-out infinite,
    beam-spike2-${t} ${(i*1.7).toFixed(1)}s ease-in-out infinite,
    beam-fade-out-${t} 0.5s ease forwards;
}

[data-beam="${t}"][data-active]::after,
[data-beam="${t}"][data-fading]::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${h}px;
  padding: ${r}px;
  clip-path: inset(0 round ${n}px);
  background: ${C}, ${w};
  -webkit-mask:
    radial-gradient(
      ellipse calc(78px * var(--beam-w-${t})) calc(60px * var(--beam-h-${t})) at calc(var(--beam-x-${t}) * 100%) 100%,
      white 0%, rgba(255, 255, 255, 0.5) 45%, transparent 100%
    ),
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  -webkit-mask-composite: source-in, xor;
  mask:
    radial-gradient(
      ellipse calc(78px * var(--beam-w-${t})) calc(60px * var(--beam-h-${t})) at calc(var(--beam-x-${t}) * 100%) 100%,
      white 0%, rgba(255, 255, 255, 0.5) 45%, transparent 100%
    ),
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  mask-composite: intersect, exclude;
  pointer-events: none;
  z-index: 2;
  opacity: calc(var(--beam-opacity-${t}) * var(--beam-edge-${t}) * ${_.toFixed(2)} * var(--beam-stroke-opacity, 1) * var(--beam-strength, 1));
  ${b}
}

[data-beam="${t}"][data-active]::before,
[data-beam="${t}"][data-fading]::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: ${n}px;
  background: ${T};
  box-shadow: inset 0 0 9px 1px ${c};
  -webkit-mask-image:
    radial-gradient(
      ellipse calc(78px * var(--beam-w-${t})) calc(60px * var(--beam-h-${t})) at calc(var(--beam-x-${t}) * 100%) 100%,
      white 0%, rgba(255, 255, 255, 0.5) 45%, transparent 100%
    ),
    linear-gradient(white, transparent 28px, transparent calc(100% - 28px), white),
    linear-gradient(to right, white, transparent 28px, transparent calc(100% - 28px), white);
  -webkit-mask-composite: source-in, source-over;
  mask-image:
    radial-gradient(
      ellipse calc(78px * var(--beam-w-${t})) calc(60px * var(--beam-h-${t})) at calc(var(--beam-x-${t}) * 100%) 100%,
      white 0%, rgba(255, 255, 255, 0.5) 45%, transparent 100%
    ),
    linear-gradient(white, transparent 28px, transparent calc(100% - 28px), white),
    linear-gradient(to right, white, transparent 28px, transparent calc(100% - 28px), white);
  mask-composite: intersect, add;
  pointer-events: none;
  z-index: 1;
  opacity: calc(var(--beam-opacity-${t}) * var(--beam-edge-${t}) * ${v.toFixed(2)} * var(--beam-inner-opacity, 1) * var(--beam-strength, 1));
  clip-path: inset(0 round ${n}px);
  ${b}
}

[data-beam="${t}"] [data-beam-bloom] {
  display: none;
  position: absolute;
  inset: 0;
  border-radius: ${h}px;
  clip-path: inset(0 round ${n}px);
  padding: 0;
  -webkit-mask: radial-gradient(
    ellipse calc(84px * var(--beam-w-${t})) calc(110px * var(--beam-h-${t})) at calc(var(--beam-x-${t}) * 100%) 100%,
    white 0%, rgba(255, 255, 255, 0.5) 35%, transparent 100%
  );
  -webkit-mask-composite: source-over;
  mask: radial-gradient(
    ellipse calc(84px * var(--beam-w-${t})) calc(110px * var(--beam-h-${t})) at calc(var(--beam-x-${t}) * 100%) 100%,
    white 0%, rgba(255, 255, 255, 0.5) 35%, transparent 100%
  );
  mask-composite: add;
  background: ${E};
  ${D}
  pointer-events: none;
  z-index: 3;
  opacity: 0;
}

[data-beam="${t}"][data-active] [data-beam-bloom],
[data-beam="${t}"][data-fading] [data-beam-bloom] {
  display: block;
  opacity: calc(var(--beam-opacity-${t}) * var(--beam-edge-${t}) * ${y.toFixed(2)} * var(--beam-bloom-opacity, 1) * var(--beam-strength, 1));
  ${x}
}

@keyframes beam-travel-${t} {
  0%   { --beam-x-${t}: 0.06;  --beam-w-${t}: 0.5; }
  10%  { --beam-x-${t}: 0.15;  --beam-w-${t}: 0.8; }
  20%  { --beam-x-${t}: 0.25;  --beam-w-${t}: 1.1; }
  30%  { --beam-x-${t}: 0.35;  --beam-w-${t}: 1.3; }
  40%  { --beam-x-${t}: 0.44;  --beam-w-${t}: 1.45; }
  50%  { --beam-x-${t}: 0.5;   --beam-w-${t}: 1.5; }
  60%  { --beam-x-${t}: 0.56;  --beam-w-${t}: 1.45; }
  70%  { --beam-x-${t}: 0.65;  --beam-w-${t}: 1.3; }
  80%  { --beam-x-${t}: 0.75;  --beam-w-${t}: 1.1; }
  90%  { --beam-x-${t}: 0.85;  --beam-w-${t}: 0.8; }
  100% { --beam-x-${t}: 0.94;  --beam-w-${t}: 0.5; }
}

@keyframes beam-edge-fade-${t} {
  0%    { --beam-edge-${t}: 0; }
  12.5% { --beam-edge-${t}: 0; }
  32.5% { --beam-edge-${t}: 1; }
  67.5% { --beam-edge-${t}: 1; }
  87.5% { --beam-edge-${t}: 0; }
  100%  { --beam-edge-${t}: 0; }
}

@keyframes beam-breathe-${t} {
  0%, 100% { --beam-h-${t}: 0.8; }
  25%      { --beam-h-${t}: 1.25; }
  55%      { --beam-h-${t}: 0.85; }
  80%      { --beam-h-${t}: 1.3; }
}

@keyframes beam-spike-${t} {
  0%   { --beam-spike-${t}: 0.8; }
  25%  { --beam-spike-${t}: 1.3; }
  50%  { --beam-spike-${t}: 0.9; }
  75%  { --beam-spike-${t}: 1.4; }
  100% { --beam-spike-${t}: 0.8; }
}

@keyframes beam-spike2-${t} {
  0%   { --beam-spike2-${t}: 1.2; }
  25%  { --beam-spike2-${t}: 0.7; }
  50%  { --beam-spike2-${t}: 1.4; }
  75%  { --beam-spike2-${t}: 0.8; }
  100% { --beam-spike2-${t}: 1.2; }
}

@keyframes beam-fade-in-${t} {
  to { --beam-opacity-${t}: 1; }
}

@keyframes beam-fade-out-${t} {
  from { --beam-opacity-${t}: 1; }
  to { --beam-opacity-${t}: 0; }
}
${S}
${X(t)}
`}var zt=new Set,Z=null,Bt=0,Vt=1e3/30-2,Ht=Math.PI*2;function Ut(e){return(1-Math.cos(Ht*e))/2}function Wt(e){if(Z=requestAnimationFrame(Wt),e-Bt<Vt)return;Bt=e;let t=e/1e3;zt.forEach(({el:e,config:n})=>{for(let r of n.oscillators){let n=(t-r.delay)/r.period,i=r.a+(r.b-r.a)*Ut(n);e.style.setProperty(r.prop,r.unit===`px`?`${i.toFixed(2)}px`:i.toFixed(4))}if(n.hue){let{prop:r,range:i,period:a,continuous:o}=n.hue,s=o?t/a%1*i:-i+2*i*Ut(t/a);e.style.setProperty(r,`${s.toFixed(2)}deg`)}})}function Gt(){Z??=(Bt=0,requestAnimationFrame(Wt))}function Kt(){zt.size===0&&Z!=null&&(cancelAnimationFrame(Z),Z=null)}function qt(e,t){let n={el:e,config:t};return zt.add(n),Gt(),()=>{zt.delete(n),Kt()}}function Jt(){let[e,t]=G(()=>typeof window>`u`||window.matchMedia(`(prefers-color-scheme: dark)`).matches?`dark`:`light`);return K(()=>{if(typeof window>`u`)return;let e=window.matchMedia(`(prefers-color-scheme: dark)`),n=e=>{t(e.matches?`dark`:`light`)};return e.addEventListener(`change`,n),()=>e.removeEventListener(`change`,n)},[]),e}function Yt(e,t){return e===`auto`?t:e}var Xt=Me(function({children:e,size:t=`md`,colorVariant:n=`colorful`,theme:r=`dark`,staticColors:i=!1,duration:a,active:o=!0,borderRadius:s,brightness:c,saturation:l,hueRange:u=30,strength:d=1,className:f,style:p,onActivate:m,onDeactivate:h,onAnimationEnd:g,..._},v){let y=ye().replace(/:/g,`-`),b=Jt(),x=ge(null),[C,w]=G(o),[T,E]=G(!1),[D,O]=G(!0),[ee,k]=G(null),[A,j]=G({x:1,y:1});K(()=>{if(s!=null)return;let e=x.current;if(!e)return;let t=()=>{let t=e.firstElementChild;if(!t)return;let n=getComputedStyle(t),r=parseFloat(n.borderTopLeftRadius);!isNaN(r)&&r>0&&k(r)};t();let n=new MutationObserver(t);return n.observe(e,{childList:!0,subtree:!1}),()=>n.disconnect()},[s,e]),K(()=>{o&&!C&&!T?w(!0):!o&&C&&!T&&E(!0)},[o,C,T]),K(()=>{let e=x.current;if(!e||typeof IntersectionObserver>`u`)return;let t=new IntersectionObserver(e=>{for(let t of e)O(t.isIntersecting)},{rootMargin:`256px`});return t.observe(e),()=>t.disconnect()},[]),K(()=>{if(t!==`pulse-outside`){j({x:1,y:1});return}let e=x.current;if(!e)return;let n=e=>Math.max(.35,Math.min(4,e)),r=()=>{let t=e.firstElementChild;if(!t)return;let r=t.getBoundingClientRect();if(!r.width||!r.height)return;let i=+n(r.width/350).toFixed(3),a=+n(r.height/140).toFixed(3);j(e=>e.x===i&&e.y===a?e:{x:i,y:a})};if(r(),typeof ResizeObserver>`u`)return;let i=e.firstElementChild;if(!i)return;let a=new ResizeObserver(r);return a.observe(i),()=>a.disconnect()},[t,e]);let M=ve(e=>{let t=e.animationName;t.includes(`fade-out`)?(w(!1),E(!1),h?.()):t.includes(`fade-in`)&&m?.(),g?.(e)},[m,h,g]),N=Yt(r,b),P=rt[t][N],F=nt[t],I=t===`pulse-inner`||t===`pulse-outside`,te=s??ee??F.borderRadius,L=a??(t===`line`?3.1:I?2.3:1.96),ne=l??P.saturation,re=c??P.brightness??1.3,R=t===`line`?Math.min(u,13):u,z=n===`mono`||i,ie=_e(()=>Nt({id:y,borderRadius:te,borderWidth:F.borderWidth,duration:L,strokeOpacity:P.strokeOpacity,innerOpacity:P.innerOpacity,bloomOpacity:P.bloomOpacity,innerShadow:P.innerShadow,size:t,colorVariant:n,staticColors:z,brightness:re,saturation:ne,hueRange:R,theme:N,hairlineOpacity:P.hairlineOpacity}),[y,te,F.borderWidth,L,P.strokeOpacity,P.innerOpacity,P.bloomOpacity,P.innerShadow,P.hairlineOpacity,t,n,z,re,ne,R,N]),B=_e(()=>I?jt(t,N,L,R,z,y):null,[I,t,N,L,R,z,y]);K(()=>{var e;if(!B||!(C||T)||!D)return;let t=x.current;if(t&&!(typeof window<`u`&&(e=window.matchMedia)!=null&&e.call(window,`(prefers-reduced-motion: reduce)`).matches))return qt(t,B)},[B,C,T,D]);let V=ve(e=>{x.current=e,typeof v==`function`?v(e):v&&(v.current=e)},[v]),H={...p??{},"--beam-strength":Math.max(0,Math.min(1,d)),...t===`pulse-outside`?{"--pulse-glow-sx":A.x,"--pulse-glow-sy":A.y}:{}};return q(S,{children:[q(`style`,{children:ie}),q(`div`,{..._,ref:V,"data-beam":y,"data-active":C&&!T?``:void 0,"data-fading":T?``:void 0,"data-paused":C&&!T&&!D?``:void 0,className:f,style:H,onAnimationEnd:M,children:[e,q(`div`,{"data-beam-bloom":!0})]})]})}),Q=new Map,Zt=new Set([`sm`,`md`,`line`,`pulse-inner`,`pulse-outside`]),Qt=new Set([`colorful`,`mono`,`ocean`,`sunset`]),$t=new Set([`dark`,`light`,`auto`]),en=window.matchMedia?.(`(prefers-reduced-motion: reduce)`);function $(e,t,n,r){let i=Number(e);return Number.isFinite(i)?Math.max(n,Math.min(r,i)):t}function tn(e,t={}){let n=t.size||e.dataset.beamSize||`md`,r=t.colorVariant||t.color||e.dataset.beamColor||`sunset`,i=t.theme||e.dataset.beamTheme||`dark`,a=e.dataset.beamActive!==`false`;return{size:Zt.has(n)?n:`md`,colorVariant:Qt.has(r)?r:`sunset`,theme:$t.has(i)?i:`dark`,strength:$(t.strength??e.dataset.beamStrength,.35,0,1),duration:$(t.duration??e.dataset.beamDuration,3.2,.7,20),brightness:$(t.brightness??e.dataset.beamBrightness,1.08,.3,2),saturation:$(t.saturation??e.dataset.beamSaturation,.92,0,2),hueRange:$(t.hueRange??e.dataset.beamHueRange,12,0,90),borderRadius:$(t.borderRadius??e.dataset.beamRadius,12,0,80),active:!!(t.active??a)&&!en?.matches}}function nn({options:e}){return q(Xt,{...e,className:`vp-border-beam-overlay`,"aria-hidden":`true`,children:q(`span`,{className:`vp-border-beam-surface`})})}function rn(e){let t=Q.get(e);if(t)return t;let n=document.createElement(`span`);return n.className=`vp-border-beam-mount`,n.setAttribute(`aria-hidden`,`true`),e.classList.add(`vp-border-beam-host`),e.prepend(n),t={mount:n,root:et(n)},Q.set(e,t),t}function an(e,t={}){if(!e||e.dataset.beamFailed===`true`)return!1;try{return rn(e).root.render(q(nn,{options:tn(e,t)})),!0}catch(t){return e.dataset.beamFailed=`true`,console.warn(`Border beam unavailable`,t),!1}}function on(e,t={}){return e?(t.size!=null&&(e.dataset.beamSize=String(t.size)),(t.colorVariant!=null||t.color!=null)&&(e.dataset.beamColor=String(t.colorVariant??t.color)),t.theme!=null&&(e.dataset.beamTheme=String(t.theme)),t.strength!=null&&(e.dataset.beamStrength=String(t.strength)),t.duration!=null&&(e.dataset.beamDuration=String(t.duration)),t.brightness!=null&&(e.dataset.beamBrightness=String(t.brightness)),t.saturation!=null&&(e.dataset.beamSaturation=String(t.saturation)),t.hueRange!=null&&(e.dataset.beamHueRange=String(t.hueRange)),t.active!=null&&(e.dataset.beamActive=String(!!t.active)),an(e,t)):!1}function sn(e){if(!e)return;let t=Q.get(e);t&&(t.root.unmount(),t.mount.remove(),Q.delete(e)),e.classList.remove(`vp-border-beam-host`)}function cn(e){return e.dataset.beamActive!==`false`&&!e.classList.contains(`hidden`)&&!e.closest(`.hidden`)}function ln(e=document){if(!e)return;let t=[];e.matches?.(`[data-border-beam]`)&&t.push(e),e.querySelectorAll?.(`[data-border-beam]`).forEach(e=>t.push(e)),t.forEach(e=>cn(e)?an(e):sn(e));for(let[e]of Q)(!e.isConnected||!e.matches(`[data-border-beam]`)||!cn(e))&&sn(e)}var un=0;new MutationObserver(e=>{let t=new Set;e.forEach(e=>{e.type===`attributes`&&t.add(e.target),e.addedNodes?.forEach(e=>{e.nodeType===Node.ELEMENT_NODE&&t.add(e)})}),cancelAnimationFrame(un),un=requestAnimationFrame(()=>t.forEach(e=>ln(e)))}).observe(document.documentElement,{childList:!0,subtree:!0,attributes:!0,attributeFilter:[`class`,`data-beam-active`,`data-beam-size`,`data-beam-strength`,`data-beam-duration`,`data-beam-brightness`,`data-beam-saturation`,`data-beam-hue-range`]}),en?.addEventListener?.(`change`,()=>ln(document)),window.BorderBeamBridge={render:an,update:on,clear:sn,sync:ln},ln()})();