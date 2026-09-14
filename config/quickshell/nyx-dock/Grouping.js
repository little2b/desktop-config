// Pure state operations. Desktop IDs are kept even while an app is uninstalled.
function clean(folders) {
    var seenApps = Object.create(null), seenFolders = Object.create(null);
    return (Array.isArray(folders) ? folders : []).filter(function(f) {
        if (!f || typeof f.id !== "string" || seenFolders[f.id] || !Array.isArray(f.apps)) return false;
        seenFolders[f.id] = true;
        return true;
    }).map(function(f) {
        var apps = f.apps.filter(function(id) {
            if (typeof id !== "string" || !id || seenApps[id]) return false;
            seenApps[id] = true;
            return true;
        });
        return {id: f.id, name: String(f.name || "新建分组").slice(0, 48), apps: apps};
    }).filter(function(f) { return f.apps.length > 0; });
}

function containing(folders, appId) {
    return folders.find(function(f) { return f.apps.indexOf(appId) !== -1; });
}

function remove(folders, appId) {
    return clean(folders).map(function(f) {
        if (f.apps.indexOf(appId) === -1) return f;
        var remaining = f.apps.filter(function(id) { return id !== appId; });
        if (remaining.length < 2) return null;
        return {id: f.id, name: f.name, apps: remaining};
    }).filter(function(f) { return f !== null; });
}

function group(folders, sourceId, target, newId) {
    var current = clean(folders);
    if (!sourceId || !target || !target.id || ["app", "folder"].indexOf(target.kind) === -1 || (target.kind === "app" && sourceId === target.id)) return current;
    var dest = target.kind === "folder"
        ? current.find(function(f) { return f.id === target.id; })
        : containing(current, target.id);
    if (target.kind === "folder" && !dest) return current;
    if (dest && dest.apps.indexOf(sourceId) !== -1) return current;
    var result = remove(current, sourceId);
    if (dest) {
        return result.map(function(f) {
            return f.id === dest.id ? {id: f.id, name: f.name, apps: f.apps.concat([sourceId])} : f;
        });
    }
    result = remove(result, target.id);
    result.unshift({id: newId, name: "新建分组", apps: [target.id, sourceId]});
    return result;
}

function rename(folders, id, name) {
    var title = String(name || "").trim().slice(0, 48);
    return clean(folders).map(function(f) {
        return f.id === id && title ? {id: f.id, name: title, apps: f.apps.slice()} : f;
    });
}
